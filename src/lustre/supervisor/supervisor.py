"""Supervisor — coordinates specialist agents and manages task lifecycle.

The Supervisor is the central coordinator:
1. Receives user requests
2. Creates execution plans (via Planner)
3. Dispatches tasks to specialist agents via the bus
4. Collects results and manages confirmation gates
5. Reports back to the user
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import TYPE_CHECKING, Any, Callable

from lustre.bus.base import MessageBus
from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult
from lustre.supervisor.planner import Planner
from lustre.supervisor.state_machine import (
    ExecutionPlan,
    PlanStep,
    SupervisorState,
    SupervisorStateError,
    SupervisorStateMachine,
)

if TYPE_CHECKING:
    from lustre.agents.base import SpecialistAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------

ConfirmationCallback = Callable[[ExecutionPlan], bool]
"""Called when a plan is ready. Return True to accept, False to reject."""
ResultCallback = Callable[[dict[str, Any]], None]
"""Called when a step completes or the whole task finishes."""


class Supervisor:
    """Central coordinator for the multi-agent system.

    The Supervisor:
    - Owns the state machine
    - Owns the planner
    - Subscribes to all agent result topics
    - Dispatches tasks to agents via the bus

    Lifecycle:
        create() → start() → [handle requests] → stop()
    """

    def __init__(
        self,
        bus: MessageBus,
        agents: dict[str, SpecialistAgent],
    ) -> None:
        self.bus = bus
        self.agents = agents
        self._sm = SupervisorStateMachine()
        self._planner = Planner(bus=bus)
        self._running = False
        self._lock = threading.Lock()
        self._result_subscriptions: list[Any] = []

        # Callbacks for UI integration
        self.on_confirmation_needed: ConfirmationCallback | None = None
        self.on_step_complete: ResultCallback | None = None
        self.on_task_complete: ResultCallback | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SupervisorState:
        return self._sm.state

    @property
    def context(self) -> Any:
        return self._sm.context

    @property
    def plan(self) -> ExecutionPlan | None:
        return self._sm.context.plan

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the supervisor: subscribe to result topics."""
        with self._lock:
            if self._running:
                return
            self._running = True

        # Subscribe to ALL agent result topics (not just "code")
        for name in self.agents:
            sub = self.bus.subscribe(f"result.{name}", self._on_agent_result)
            self._result_subscriptions.append(sub)

        logger.info("Supervisor started, monitoring agents: %s", list(self.agents.keys()))

    def stop(self) -> None:
        """Stop the supervisor."""
        with self._lock:
            if not self._running:
                return
            self._running = False

            for sub in self._result_subscriptions:
                self.bus.unsubscribe(sub)
            self._result_subscriptions.clear()

        logger.info("Supervisor stopped")

    # ------------------------------------------------------------------
    # User-facing API (called from CLI)
    # ------------------------------------------------------------------

    def submit(self, user_request: str) -> ExecutionPlan:
        """Submit a new user request.

        Transitions: IDLE → PLANNING → AWAITING_CONFIRMATION
        Returns the plan for user review.

        Raises:
            SupervisorStateError: if not in IDLE state.
        """
        with self._lock:
            self._sm.submit_task(user_request)

        # Build plan
        plan = self._planner.plan(user_request)
        self._sm.set_plan(plan)

        logger.info("Plan created: %d steps, plan_id=%s", len(plan.steps), plan.plan_id)
        return plan

    def confirm_plan(self) -> None:
        """User approved the plan. Start executing.

        Transitions: AWAITING_CONFIRMATION → EXECUTING
        """
        with self._lock:
            self._sm.confirm_plan()

        # Handle the case where the first step has a confirmation gate:
        # if confirmation_points was set before we even ran it,
        # the step is still current. Remove it from confirmation_points
        # so _execute_current_step dispatches it.
        plan = self.plan
        if plan is not None:
            step = plan.current_step()
            if step is not None and step.step_id in plan.confirmation_points:
                plan.confirmation_points = [
                    cid for cid in plan.confirmation_points if cid != step.step_id
                ]

        self._execute_current_step()

    def confirm_and_continue(self) -> None:
        """Called after a mid-task confirmation. Resume execution."""
        # We are already in EXECUTING state. Just dispatch the current step.
        self._execute_current_step()

    def skip_current_step(self) -> None:
        """Skip the current step and move to the next."""
        plan = self.plan
        if plan is None:
            return

        step = plan.current_step()
        if step:
            step.status = "skipped"
            logger.info("Step %s skipped", step.step_id)

        self._advance_and_execute()

    def retry_current_step(self) -> None:
        """Retry the failed current step."""
        plan = self.plan
        if plan is None:
            return

        step = plan.current_step()
        if step and step.status == "failed":
            step.status = "pending"
            step.error = None
            self._execute_current_step()

    def request_abort(self) -> None:
        """Request abort. User confirms abort via separate /abort command."""
        try:
            self._sm.abort()
            logger.info("Task aborted")
        except SupervisorStateError:
            pass  # already idle/done

    def reset(self) -> None:
        """Reset to IDLE state and clear context."""
        self._sm.reset()

    # ------------------------------------------------------------------
    # Execution engine
    # ------------------------------------------------------------------

    def _execute_current_step(self) -> None:
        """Dispatch the current step to the appropriate agent."""
        plan = self.plan
        if plan is None:
            self._finish()
            return

        step = plan.current_step()
        if step is None:
            self._finish()
            return

        logger.debug(
            "_execute_current_step: step=%s, confirmation_points=%s",
            step.description,
            plan.confirmation_points,
        )

        # Check if we need a mid-task confirmation BEFORE running this step
        if step.step_id in plan.confirmation_points:
            # Mark as cleared so next time we don't re-ask
            plan.confirmation_points = [
                cid for cid in plan.confirmation_points if cid != step.step_id
            ]
            # We are already in AWAITING_CONFIRMATION — nothing more to do here.
            # The caller (CLI) will call confirm_and_continue() to resume.
            if self.on_confirmation_needed:
                self.on_confirmation_needed(plan)
            return

        self._dispatch_step(step)

    def _dispatch_step(self, step: PlanStep) -> None:
        """Send a task to the agent for this step."""
        plan = self.plan
        if plan is None:
            return

        agent_name = step.agent_name
        if agent_name not in self.agents:
            step.status = "failed"
            step.error = f"Unknown agent: {agent_name}"
            self._advance_and_execute()
            return

        step.status = "running"
        task_request = self._planner.create_task_request(plan, step)

        self.bus.publish(
            f"task.{agent_name}",
            Message(
                sender="supervisor",
                type=MessageType.TASK_REQUEST,
                payload=task_request.to_dict(),
                conversation_id=plan.plan_id,
            ),
        )

        logger.info(
            "Dispatched step '%s' to agent '%s' (task_id=%s)",
            step.description,
            agent_name,
            step.step_id,
        )

    def _on_agent_result(self, message: Message) -> None:
        """Handle result messages from specialist agents."""
        if not self._running:
            return

        plan = self.plan
        if plan is None:
            return

        step = plan.current_step()
        if step is None:
            return

        payload = message.payload
        task_id = payload.get("task_id", "")

        # Match result to current step
        if task_id != step.step_id:
            logger.warning(
                "Result for unexpected task_id=%s (current=%s), ignoring",
                task_id,
                step.step_id,
            )
            return

        status = payload.get("status", "failed")
        step.status = status
        step.result = payload.get("output", "")

        if payload.get("error"):
            step.error = payload["error"]
            logger.error("Step %s failed: %s", step.step_id, step.error)
        else:
            logger.info("Step '%s' completed: %s", step.description, status)

        # Notify UI
        if self.on_step_complete:
            self.on_step_complete(step.to_dict())

        # Advance to next step
        self._advance_and_execute()

    def _advance_and_execute(self) -> None:
        """Move to next pending step and execute it."""
        plan = self.plan
        if plan is None:
            return

        plan.advance()
        step = plan.current_step()

        if step is None:
            # All steps done — truly finish
            self._finish()
        else:
            # More steps to run — check if we need a mid-task confirmation gate
            if step.step_id in plan.confirmation_points:
                self._sm.request_confirmation()
                if self.on_confirmation_needed:
                    self.on_confirmation_needed(plan)
            else:
                self._dispatch_step(step)

    def _finish(self) -> None:
        """Mark the task as done."""
        self._sm.finish()
        if self.on_task_complete:
            self.on_task_complete(self._sm.context.to_dict())
        logger.info("Task completed: plan_id=%s", self.plan.plan_id if self.plan else "?")
