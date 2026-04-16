"""Message bus — inter-agent communication.

The bus is the sole communication channel between all agents.
No agent calls another agent directly — all messages go through the bus.

Supported implementations:
    MemoryMessageBus — development (in-process, threading)
    RedisMessageBus  — production (distributed, Redis Streams)
"""

from lustre.bus.base import MessageBus, Subscription
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult

try:
    from lustre.bus.redis_bus import RedisMessageBus
except Exception:  # redis not installed
    RedisMessageBus = None  # type: ignore[assignment, misc]

__all__ = [
    "Message",
    "MessageType",
    "TaskRequest",
    "TaskResult",
    "MessageBus",
    "MemoryMessageBus",
    "RedisMessageBus",
    "Subscription",
    "create_message_bus",
]


def create_message_bus(
    bus_type: str = "memory",
    **kwargs,
) -> MessageBus:
    """Create a message bus by type string.

    Args:
        bus_type: "memory" (default) or "redis"
        **kwargs: passed to the bus constructor
            For redis: url="redis://localhost:6379/0"

    Returns:
        A MessageBus instance (MemoryMessageBus or RedisMessageBus)

    Raises:
        ValueError: if bus_type is unknown or RedisMessageBus unavailable
    """
    if bus_type == "memory":
        return MemoryMessageBus(**kwargs)
    elif bus_type == "redis":
        if RedisMessageBus is None:
            raise ValueError(
                "RedisMessageBus unavailable: install redis package "
                "(pip install redis)"
            )
        return RedisMessageBus(**kwargs)
    else:
        raise ValueError(f"Unknown bus type: {bus_type!r} (use 'memory' or 'redis')")
