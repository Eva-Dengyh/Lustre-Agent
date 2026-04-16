"""Abstract MessageBus interface.

All message bus implementations (Memory, Redis, etc.) must implement
this interface so agents are decoupled from the transport layer.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from lustre.bus.message import Message


@dataclass
class Subscription:
    """A handle to an active subscription — can be cancelled."""

    id: str
    topic: str
    callback: Callable[[Message], None]
    active: bool = True


class MessageBus(ABC):
    """Abstract message bus.

    The bus is the sole communication channel between all agents.
    All agents — Supervisor and Specialists alike — communicate
    exclusively through the bus.  No agent calls another agent directly.

    Topic naming convention:
        task.<agent_name>        — Supervisor dispatches to a specific agent
        result.<agent_name>      — Agent returns result to supervisor
        broadcast                — System-wide announcements

    Example:
        >>> bus = MemoryMessageBus()
        >>> sub_id = bus.subscribe("task.code", lambda msg: print(msg))
        >>> bus.publish("task.code", Message(sender="supervisor", ...))
    """

    # ------------------------------------------------------------------
    # Core publish / subscribe
    # ------------------------------------------------------------------

    @abstractmethod
    def publish(self, topic: str, message: Message) -> None:
        """Publish a message to all subscribers of *topic*.

        Args:
            topic: The message topic (e.g. "task.code").
            message: The message to deliver.
        """
        ...

    @abstractmethod
    def subscribe(
        self, topic: str, callback: Callable[[Message], None]
    ) -> Subscription:
        """Subscribe to *topic* and call *callback* for each message.

        Returns a Subscription handle that can be used to cancel the
        subscription via unsubscribe().

        Args:
            topic: The topic to subscribe to.
            callback: A callable invoked with each incoming Message.

        Returns:
            A Subscription object.
        """
        ...

    @abstractmethod
    def unsubscribe(self, subscription: Subscription) -> None:
        """Cancel an active subscription.

        Args:
            subscription: The Subscription returned by subscribe().
        """
        ...

    # ------------------------------------------------------------------
    # Request / Response (synchronous)
    # ------------------------------------------------------------------

    @abstractmethod
    def request(
        self,
        topic: str,
        message: Message,
        timeout: float = 30.0,
    ) -> Message:
        """Send a message and wait for a single reply.

        This is a convenience wrapper around subscribe() + publish() +
        a one-shot threading.Event.  Use it when you need a synchronous
        request/response, e.g. Supervisor waiting for a task result.

        The reply message must have `reply_to` set to the original message ID.

        Args:
            topic: Destination topic.
            message: Message to send.
            timeout: Seconds to wait for a reply.

        Returns:
            The reply Message.

        Raises:
            TimeoutError: if no reply arrives within *timeout* seconds.
        """
        ...

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @abstractmethod
    def list_topics(self) -> list[str]:
        """Return all topics that currently have subscribers."""
        ...

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def wrap_response(
        self,
        request_message: Message,
        payload: dict[str, Any],
    ) -> Message:
        """Create a reply Message in response to *request_message*."""
        return Message(
            sender="",  # filled by caller
            type="task_result",
            payload=payload,
            conversation_id=request_message.conversation_id,
            recipient="supervisor",
            reply_to=request_message.id,
        )
