"""In-process message bus using Python threading primitives.

This is the development-phase implementation.  All agents run in the same
process and communicate via shared queues.  It is fast, easy to debug
(you can set breakpoints), and requires no external services.

For production use, swap this with RedisMessageBus (Phase 9) by changing
the `type` field in config.yaml.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from typing import Callable

from lustre.bus.base import MessageBus, Subscription
from lustre.bus.message import Message

logger = logging.getLogger(__name__)

DEFAULT_MAX_HOPS = 10


@dataclass
class _SubscriptionRecord:
    """Internal record for an active subscriber."""

    topic: str
    callback: Callable[[Message], None]
    active: bool = True
    lock: threading.Lock = field(default_factory=threading.Lock)


class MemoryMessageBus(MessageBus):
    """Thread-safe in-process message bus.

    Uses a dict of topic → list of subscriber records for pub/sub,
    and a per-message threading.Event for request/response waits.

    Thread safety:
        All state is protected by self._lock.  Callbacks are invoked
        inside the lock — keep them fast.  For slow callbacks, dispatch
        to a ThreadPoolExecutor (see request()).
    """

    def __init__(self, max_hops: int = DEFAULT_MAX_HOPS) -> None:
        self._max_hops = max_hops
        self._lock = threading.RLock()
        # topic -> list of _SubscriptionRecord
        self._subscribers: dict[str, list[_SubscriptionRecord]] = defaultdict(list)
        # message_id -> threading.Event (for request/response)
        self._pending_replies: dict[str, threading.Event] = {}
        self._reply_messages: dict[str, Message] = {}

    # ------------------------------------------------------------------
    # publish
    # ------------------------------------------------------------------

    def publish(self, topic: str, message: Message) -> None:
        if message.hops >= self._max_hops:
            logger.warning(
                "Message %s exceeded max_hops (%d), discarding",
                message.id,
                self._max_hops,
            )
            return

        # Deliver to all subscribers of this topic
        with self._lock:
            subscribers = list(self._subscribers.get(topic, []))
            # Also deliver to wildcard subscribers
            subscribers += list(self._subscribers.get("*", []))

        for sub in subscribers:
            if not sub.active:
                continue
            try:
                sub.callback(message)
            except Exception as exc:  # noqa: BLE001
                # Never let one broken callback crash the bus
                logger.exception("Callback raised for topic %s: %s", topic, exc)

    # ------------------------------------------------------------------
    # subscribe / unsubscribe
    # ------------------------------------------------------------------

    def subscribe(
        self, topic: str, callback: Callable[[Message], None]
    ) -> Subscription:
        with self._lock:
            record = _SubscriptionRecord(topic=topic, callback=callback)
            self._subscribers[topic].append(record)
            sub_id = str(uuid.uuid4())

        return Subscription(id=sub_id, topic=topic, callback=callback)

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            for topic, records in self._subscribers.items():
                self._subscribers[topic] = [
                    r for r in records if r.callback != subscription.callback
                ]

    # ------------------------------------------------------------------
    # request / response
    # ------------------------------------------------------------------

    def request(
        self,
        topic: str,
        message: Message,
        timeout: float = 30.0,
    ) -> Message:
        event = threading.Event()
        reply_message_holder: list[Message | None] = [None]

        def _on_reply(msg: Message) -> None:
            reply_message_holder[0] = msg
            event.set()

        # Subscribe temporarily for the reply
        reply_sub = self.subscribe(f"result.{message.sender}", _on_reply)
        try:
            # Also wait on the direct reply_to mechanism
            with self._lock:
                self._pending_replies[message.id] = event

            self.publish(topic, message)

            if not event.wait(timeout=timeout):
                raise TimeoutError(
                    f"request timed out after {timeout}s "
                    f"(topic={topic}, msg_id={message.id})"
                )

            reply = reply_message_holder[0]
            if reply is None:
                raise TimeoutError(f"No reply received for message {message.id}")
            return reply

        finally:
            self.unsubscribe(reply_sub)
            with self._lock:
                self._pending_replies.pop(message.id, None)

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    def list_topics(self) -> list[str]:
        with self._lock:
            return list(self._subscribers.keys())

    # ------------------------------------------------------------------
    # dispatch helpers (for use by other modules)
    # ------------------------------------------------------------------

    def dispatch(self, topic: str, message: Message) -> None:
        """Alias for publish — for readability in agent code."""
        self.publish(topic, message)
