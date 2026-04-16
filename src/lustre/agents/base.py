"""Base class for all Specialist agents.

A Specialist is an agent that:
1. Subscribes to a task topic on the message bus
2. Receives TaskRequest messages
3. Processes them (in Phase 2: just returns mock; Phase 4: calls LLM)
4. Publishes TaskResult back to the result topic
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult

if TYPE_CHECKING:
    from lustre.bus.base import MessageBus

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for a Specialist agent."""

    name: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    api_key: str | None = None


class SpecialistAgent(ABC):
    """Base class for all Specialist agents.

    Each specialist listens on its own task topic (task.<name>) and
    responds by publishing to result.<name>.

    Lifecycle:
        create() → start() → [handles tasks] → stop()

    Subclasses must implement:
        process_task() — the actual work logic (will call LLM in Phase 4)
    """

    def __init__(
        self,
        config: AgentConfig,
        bus: MessageBus,
    ) -> None:
        self.config = config
        self.bus = bus
        self._running = False
        self._lock = threading.Lock()
        self._subscription = None  # set by start()

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start listening for tasks on the message bus."""
        with self._lock:
            if self._running:
                logger.warning("Agent %s already started", self.name)
                return
            self._running = True

        topic = f"task.{self.name}"
        self._subscription = self.bus.subscribe(topic, self._on_message)
        logger.info("Agent %s started, listening on %s", self.name, topic)

    def stop(self) -> None:
        """Stop listening for tasks."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._subscription is not None:
            self.bus.unsubscribe(self._subscription)
            self._subscription = None

        logger.info("Agent %s stopped", self.name)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _on_message(self, message: Message) -> None:
        """Handler for incoming task messages — runs in bus thread."""
        if not self._running:
            return

        logger.info(
            "Agent %s received task: %s",
            self.name,
            message.payload.get("task_id", "?"),
        )

        try:
            task_request = self._parse_task_request(message)
        except Exception as exc:
            logger.exception("Agent %s failed to parse task: %s", self.name, exc)
            self._publish_error(message, str(exc))
            return

        try:
            result = self.process_task(task_request)
        except Exception as exc:
            logger.exception("Agent %s failed to process task: %s", self.name, exc)
            result = TaskResult(
                task_id=task_request.task_id,
                status="failed",
                error=str(exc),
                agent_name=self.name,
            )

        self._publish_result(message, result)

    def _parse_task_request(self, message: Message) -> TaskRequest:
        """Parse Message.payload into a TaskRequest."""
        payload = message.payload
        return TaskRequest(
            task_id=payload["task_id"],
            description=payload["description"],
            context=payload.get("context", {}),
            skills_requested=payload.get("skills_requested", []),
            confirmation_needed=payload.get("confirmation_needed", False),
            confirmation_prompt=payload.get("confirmation_prompt"),
            priority=payload.get("priority", 0),
        )

    def _publish_result(
        self, request_message: Message, result: TaskResult
    ) -> None:
        """Publish TaskResult back to the supervisor."""
        result.agent_name = self.name
        reply = Message(
            sender=self.name,
            type=MessageType.TASK_RESULT,
            payload=result.to_dict(),
            conversation_id=request_message.conversation_id,
            recipient="supervisor",
            reply_to=request_message.id,
        )
        self.bus.publish(f"result.{self.name}", reply)
        logger.info(
            "Agent %s published result for task %s: %s",
            self.name,
            result.task_id,
            result.status,
        )

    def _publish_error(self, request_message: Message, error: str) -> None:
        """Publish an error result when parsing or processing fails."""
        result = TaskResult(
            task_id=request_message.payload.get("task_id", "unknown"),
            status="failed",
            error=f"Parse/handle error: {error}",
            agent_name=self.name,
        )
        self._publish_result(request_message, result)

    # ------------------------------------------------------------------
    # Abstract work logic
    # ------------------------------------------------------------------

    @abstractmethod
    def process_task(self, task: TaskRequest) -> TaskResult:
        """Process a task and return the result.

        Subclasses implement this to define actual agent behavior.
        In Phase 4, this will call the LLM.

        Args:
            task: The parsed task request.

        Returns:
            TaskResult with status, output, artifacts.
        """
        ...
