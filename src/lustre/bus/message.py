"""Message and task data classes for the message bus."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """Message types in the lustre system."""

    # Supervisor → Specialist
    TASK_REQUEST = "task_request"
    ABORT = "abort"
    RETRY = "retry"

    # Specialist → Supervisor
    TASK_RESULT = "task_result"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

    # System
    HUMAN_CONFIRMATION = "human_confirmation"
    SYSTEM_SHUTDOWN = "system_shutdown"


@dataclass
class Message:
    """A message sent between agents via the message bus.

    Attributes:
        id: Unique identifier for this message.
        sender: Name of the sending agent (e.g., "supervisor", "code").
        recipient: Name of the receiving agent. None means broadcast.
        type: Message type (see MessageType).
        payload: Message body — dict with type-specific data.
        conversation_id: Groups messages belonging to the same task.
        timestamp: When the message was created.
        hops: Number of times this message has been forwarded (for loop detection).
        reply_to: ID of the message this is replying to.
        metadata: Additional arbitrary metadata.
    """

    sender: str
    type: MessageType | str
    payload: dict[str, Any]
    conversation_id: str
    recipient: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    hops: int = 0
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def increment_hops(self) -> Message:
        """Return a new Message with hops incremented by 1."""
        return Message(
            id=self.id,
            sender=self.sender,
            recipient=self.recipient,
            type=self.type,
            payload=self.payload,
            conversation_id=self.conversation_id,
            timestamp=self.timestamp,
            hops=self.hops + 1,
            reply_to=self.reply_to,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (for testing / serialization)."""
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "type": self.type if isinstance(self.type, str) else self.type.value,
            "payload": self.payload,
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp.isoformat(),
            "hops": self.hops,
            "reply_to": self.reply_to,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Deserialize from a plain dict."""
        data = dict(data)
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        if "type" in data:
            try:
                data["type"] = MessageType(data["type"])
            except ValueError:
                pass  # keep as string
        return cls(**data)


@dataclass
class TaskRequest:
    """Payload for a task dispatched from Supervisor to a Specialist."""

    task_id: str
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    skills_requested: list[str] = field(default_factory=list)
    confirmation_needed: bool = False
    confirmation_prompt: str | None = None
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "context": self.context,
            "skills_requested": self.skills_requested,
            "confirmation_needed": self.confirmation_needed,
            "confirmation_prompt": self.confirmation_prompt,
            "priority": self.priority,
        }


@dataclass
class TaskResult:
    """Payload returned from a Specialist to the Supervisor."""

    task_id: str
    status: str  # "completed" | "failed" | "partial"
    output: str = ""
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)  # path → content
    agent_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
            "agent_name": self.agent_name,
        }
