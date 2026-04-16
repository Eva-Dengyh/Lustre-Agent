"""State machine for the Supervisor.

Defines the states and transitions for the supervisor's lifecycle.
The supervisor orchestrates specialist agents and coordinates
human-in-the-loop confirmation gates.

State diagram:
                                          /abort
    ┌──────────────────────────────────────────┐
    │                                          │
    ▼                                          │
  IDLE ──── user submits task ────▶ PLANNING ──┼── user confirms ───▶ EXECUTING
    ▲                                        │ │                             │
    │                                        │ │ /abort                      │
    │                                        ▼ ▼                             │
    │                                   AWAITING_CONFIRMATION ───────────▶    │
    │                                                                            │
    └────────────────────────────── done / reset ───────────────────────────────┘
                                           /
                                         /abort ──────────────────────────────▶ ABORTED
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class SupervisorState(str, enum.Enum):
    """All possible states of the Supervisor."""

    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    DONE = "done"
    ABORTED = "aborted"


@dataclass
class PlanStep:
    """A single step in a task execution plan."""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    agent_name: str = ""  # which specialist handles this
    status: str = "pending"  # pending | running | completed | failed | skipped
    result: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "agent_name": self.agent_name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class ExecutionPlan:
    """A complete plan produced by the Planner."""

    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_request: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    agent_assignments: dict[str, str] = field(default_factory=dict)  # agent_name → role
    confirmation_points: list[str] = field(default_factory=list)  # step_ids that need human OK
    created_at: datetime = field(default_factory=datetime.now)
    current_step_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "original_request": self.original_request,
            "steps": [s.to_dict() for s in self.steps],
            "agent_assignments": self.agent_assignments,
            "confirmation_points": self.confirmation_points,
            "current_step_index": self.current_step_index,
        }

    def current_step(self) -> PlanStep | None:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def advance(self) -> None:
        """Move to next step that needs execution."""
        self.current_step_index += 1
        while (
            self.current_step_index < len(self.steps)
            and self.steps[self.current_step_index].status in ("completed", "skipped")
        ):
            self.current_step_index += 1


@dataclass
class TaskContext:
    """Mutable context for an active task session."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_request: str = ""
    plan: ExecutionPlan | None = None
    state: SupervisorState = SupervisorState.IDLE
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "plan": self.plan.to_dict() if self.plan else None,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "metadata": self.metadata,
        }


class SupervisorStateMachine:
    """State machine managing supervisor lifecycle transitions.

    All state changes go through this class so transitions are
    always valid and observable.

    Usage:
        sm = SupervisorStateMachine()
        sm.submit_task("帮我写一个 API")
        sm.confirm_plan()
        sm.execute_next_step()
        sm.finish()
    """

    def __init__(self) -> None:
        self._state = SupervisorState.IDLE
        self._context = TaskContext()
        self._history: list[SupervisorState] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SupervisorState:
        return self._state

    @property
    def context(self) -> TaskContext:
        return self._context

    @property
    def is_idle(self) -> bool:
        return self._state == SupervisorState.IDLE

    @property
    def is_active(self) -> bool:
        """True when there is a task in progress (not idle/done/aborted)."""
        return self._state not in (
            SupervisorState.IDLE,
            SupervisorState.DONE,
            SupervisorState.ABORTED,
        )

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def submit_task(self, user_request: str) -> None:
        """Transition: IDLE → PLANNING. Called when user submits a new task."""
        if self._state != SupervisorState.IDLE:
            raise SupervisorStateError(
                f"Cannot submit task from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.PLANNING
        self._context = TaskContext(user_request=user_request)
        self._context.state = self._state

    def set_plan(self, plan: ExecutionPlan) -> None:
        """Transition: PLANNING → AWAITING_CONFIRMATION. Plan is ready for review."""
        if self._state != SupervisorState.PLANNING:
            raise SupervisorStateError(
                f"Cannot set plan from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.AWAITING_CONFIRMATION
        self._context.plan = plan
        self._context.state = self._state

    def confirm_plan(self) -> None:
        """Transition: AWAITING_CONFIRMATION → EXECUTING. User approved the plan."""
        if self._state != SupervisorState.AWAITING_CONFIRMATION:
            raise SupervisorStateError(
                f"Cannot confirm plan from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.EXECUTING
        self._context.state = self._state

    def request_confirmation(self) -> None:
        """Transition: EXECUTING → AWAITING_CONFIRMATION. Need mid-task human approval."""
        if self._state != SupervisorState.EXECUTING:
            raise SupervisorStateError(
                f"Cannot request confirmation from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.AWAITING_CONFIRMATION
        self._context.state = self._state

    def finish(self) -> None:
        """Transition: EXECUTING → DONE. Task completed successfully."""
        if self._state not in (SupervisorState.EXECUTING, SupervisorState.PLANNING):
            raise SupervisorStateError(
                f"Cannot finish from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.DONE
        self._context.state = self._state

    def abort(self) -> None:
        """Transition: any active state → ABORTED."""
        if self._state in (SupervisorState.IDLE, SupervisorState.DONE, SupervisorState.ABORTED):
            raise SupervisorStateError(
                f"Cannot abort from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.ABORTED
        self._context.state = self._state

    def reset(self) -> None:
        """Transition: DONE/ABORTED → IDLE. Clear context and start fresh."""
        if self._state not in (SupervisorState.DONE, SupervisorState.ABORTED):
            raise SupervisorStateError(
                f"Cannot reset from state {self._state.value}"
            )
        self._history.append(self._state)
        self._state = SupervisorState.IDLE
        self._context = TaskContext()
        self._context.state = self._state

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def state_history(self) -> list[SupervisorState]:
        """Return the history of states visited (excludes initial IDLE)."""
        return list(self._history)


class SupervisorStateError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass
