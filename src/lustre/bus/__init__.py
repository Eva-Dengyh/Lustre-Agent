"""Message bus — inter-agent communication.

The bus is the sole communication channel between all agents.
No agent calls another agent directly — all messages go through the bus.
"""

from lustre.bus.base import MessageBus, Subscription
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult

__all__ = [
    "Message",
    "MessageType",
    "TaskRequest",
    "TaskResult",
    "MessageBus",
    "MemoryMessageBus",
    "Subscription",
]
