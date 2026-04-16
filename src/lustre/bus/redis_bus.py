"""Redis-backed distributed message bus using Redis Streams.

Uses Redis Streams (XADD/XREAD) for durable, ordered message delivery.
Each topic maps to a Redis Stream key.  Subscribers read with XREAD BLOCK
so they receive messages in real-time.  Supports request/response via
temporary reply streams.

Usage:
    # Development: MemoryMessageBus (default)
    bus = MemoryMessageBus()

    # Production: RedisMessageBus (swap in config.yaml)
    bus = RedisMessageBus(url="redis://localhost:6379/0")

    # Agents don't know which bus is being used — interface is identical.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import redis

from lustre.bus.base import MessageBus, Subscription
from lustre.bus.message import Message

logger = logging.getLogger(__name__)


def _dumps(msg: Message) -> str:
    return json.dumps(msg.to_dict(), ensure_ascii=False, default=str)


def _loads(data: str | bytes) -> Message:
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return Message.from_dict(json.loads(data))


# Max stream length per topic (prevent unbounded growth)
MAX_STREAM_LEN = 100_000
# Consumer group name (all lustre subscribers share one group per stream)
CONSUMER_GROUP = "lustre-subscribers"


# ---------------------------------------------------------------------------
# RedisMessageBus
# ---------------------------------------------------------------------------

class RedisMessageBus(MessageBus):
    """Distributed message bus backed by Redis Streams.

    Each topic maps to a Redis Stream: ``lustre:stream:<topic>``.
    Subscribers use consumer groups so messages are load-balanced
    across multiple processes reading the same stream.

    Thread safety:
        All Redis operations are thread-safe.  Subscription management
        uses a Python-level lock.  Callbacks are invoked in the subscriber
        background thread — keep them fast or dispatch to a thread pool.

    Design:
        publish  → XADD to the topic stream
        subscribe → XREADGROUP from the stream (blocking background thread)
        request  → XADD request + XREAD from a temporary reply stream
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        max_stream_len: int = MAX_STREAM_LEN,
        subscriber_timeout_ms: int = 5000,
    ) -> None:
        self._url = url
        self._max_stream_len = max_stream_len
        self._subscriber_timeout_ms = subscriber_timeout_ms

        # Lazy connection — created on first use
        self._pool: redis.ConnectionPool | None = None
        self._subscriber_conn: redis.Redis | None = None

        # Subscription management (in-process)
        self._lock = threading.RLock()
        self._subscriptions: dict[str, dict[str, Callable[[Message], None]]] = {}
        # topic → {subscription_id → callback}
        self._sub_threads: dict[str, threading.Thread] = {}
        # topic → running flag
        self._sub_running: dict[str, threading.Event] = {}
        # subscription_id → (topic, callback) for lookup during unsubscribe
        self._sub_info: dict[str, tuple[str, Callable[[Message], None]]] = {}

        # Per-connection lock for subscriber connection (single-threaded read)
        self._sub_lock = threading.RLock()

        # Track consumer name for this process (must be unique per process)
        self._consumer_name = f"consumer-{uuid.uuid4().hex[:8]}"

    # -------------------------------------------------------------------------
    # Connection management
    # -------------------------------------------------------------------------

    @property
    def _redis(self) -> redis.Redis:
        if self._pool is None:
            self._pool = redis.ConnectionPool.from_url(
                self._url, decode_responses=False
            )
        return redis.Redis(connection_pool=self._pool)

    def _get_subscriber_conn(self) -> redis.Redis:
        if self._subscriber_conn is None:
            self._subscriber_conn = redis.Redis(
                connection_pool=self._pool,
                decode_responses=False,
            )
        return self._subscriber_conn

    # -------------------------------------------------------------------------
    # Stream helpers
    # -------------------------------------------------------------------------

    def _stream_key(self, topic: str) -> str:
        return f"lustre:stream:{topic}"

    def _reply_stream_key(self, msg_id: str) -> str:
        return f"lustre:reply:{msg_id}"

    # -------------------------------------------------------------------------
    # publish
    # -------------------------------------------------------------------------

    def publish(self, topic: str, message: Message) -> None:
        if message.hops >= 10:
            logger.warning("Message %s exceeded max_hops, discarding", message.id)
            return

        stream_key = self._stream_key(topic)
        try:
            self._redis.xadd(
                stream_key,
                {"data": _dumps(message)},
                maxlen=self._max_stream_len,
                approximate=True,
            )
        except redis.RedisError:
            logger.exception("Failed to publish to topic %s", topic)

    # -------------------------------------------------------------------------
    # subscribe / unsubscribe
    # -------------------------------------------------------------------------

    def subscribe(
        self, topic: str, callback: Callable[[Message], None]
    ) -> Subscription:
        stream_key = self._stream_key(topic)
        sub_id = str(uuid.uuid4())

        # Register callback
        with self._lock:
            if topic not in self._subscriptions:
                self._subscriptions[topic] = {}
                self._sub_running[topic] = threading.Event()
            self._subscriptions[topic][sub_id] = callback
            self._sub_info[sub_id] = (topic, callback)

        # Ensure consumer group exists
        try:
            self._redis.xgroup_create(
                stream_key, CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as exc:
            # Group already exists — that's fine
            if "BUSYGROUP" not in str(exc):
                raise

        # Start background reader thread if not already running
        with self._lock:
            if topic not in self._sub_threads:
                self._sub_running[topic].set()
                t = threading.Thread(
                    target=self._reader_loop,
                    args=(topic,),
                    name=f"redis-sub-{topic}",
                    daemon=True,
                )
                self._sub_threads[topic] = t
                t.start()

        return Subscription(id=sub_id, topic=topic, callback=callback)

    def unsubscribe(self, subscription: Subscription) -> None:
        sub_id = subscription.id
        with self._lock:
            info = self._sub_info.pop(sub_id, None)
            if info is None:
                return
            topic, _ = info
            if topic in self._subscriptions:
                self._subscriptions[topic].pop(sub_id, None)
                # If no more subscribers for this topic, stop the reader
                if not self._subscriptions[topic]:
                    self._sub_running[topic].clear()
                    self._subscriptions.pop(topic, None)
                    self._sub_threads.pop(topic, None)
                    self._sub_running.pop(topic, None)

    def _reader_loop(self, topic: str) -> None:
        """Background thread: reads from Redis stream and dispatches callbacks."""
        stream_key = self._stream_key(topic)
        conn = self._get_subscriber_conn()
        running = self._sub_running[topic]

        last_id = "$"  # only new messages

        while running.is_set():
            try:
                # XREADGROUP BLOCK: wait for new messages, 5s timeout
                messages = conn.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=self._consumer_name,
                    streams={stream_key: last_id},
                    count=10,
                    block=self._subscriber_timeout_ms,
                )
            except redis.RedisError:
                logger.exception("XREADGROUP error on topic %s", topic)
                continue

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for msg_id, fields in stream_messages:
                    last_id = msg_id
                    data = fields.get(b"data", b"")
                    if not data:
                        continue
                    try:
                        message = _loads(data)
                    except Exception:
                        logger.exception("Failed to deserialize message")
                        continue

                    # Dispatch to all callbacks for this topic
                    with self._lock:
                        cbs = list(self._subscriptions.get(topic, {}).values())

                    for cb in cbs:
                        if not running.is_set():
                            break
                        try:
                            cb(message)
                        except Exception:
                            logger.exception("Callback raised for topic %s", topic)

    # -------------------------------------------------------------------------
    # request / response
    # -------------------------------------------------------------------------

    def request(
        self,
        topic: str,
        message: Message,
        timeout: float = 30.0,
    ) -> Message:
        reply_stream_key = self._reply_stream_key(message.id)
        reply_received = threading.Event()
        reply_holder: list[Message | None] = [None]
        timeout_ms = int(timeout * 1000)

        def _on_reply(msg: Message) -> None:
            reply_holder[0] = msg
            reply_received.set()

        # Subscribe to reply stream (one-shot)
        reply_sub = self.subscribe(reply_stream_key, _on_reply)
        try:
            self.publish(topic, message)

            if not reply_received.wait(timeout=timeout):
                raise TimeoutError(
                    f"request timed out after {timeout}s "
                    f"(topic={topic}, msg_id={message.id})"
                )

            reply = reply_holder[0]
            if reply is None:
                raise TimeoutError(f"No reply for message {message.id}")
            return reply

        finally:
            self.unsubscribe(reply_sub)

    # -------------------------------------------------------------------------
    # introspection
    # -------------------------------------------------------------------------

    def list_topics(self) -> list[str]:
        """Return topics that have active subscribers."""
        with self._lock:
            return list(self._subscriptions.keys())

    # -------------------------------------------------------------------------
    # lifecycle
    # -------------------------------------------------------------------------

    def close(self) -> None:
        """Stop all subscriber threads and close Redis connections."""
        # Stop all subscriber threads
        with self._lock:
            for topic in list(self._sub_running.keys()):
                self._sub_running[topic].clear()

            for t in list(self._sub_threads.values()):
                t.join(timeout=2)

            self._subscriptions.clear()
            self._sub_threads.clear()
            self._sub_running.clear()
            self._sub_info.clear()

        # Close Redis connections
        if self._subscriber_conn:
            self._subscriber_conn.close()
            self._subscriber_conn = None
        if self._pool:
            self._pool.disconnect()
            self._pool = None

    def __repr__(self) -> str:
        return f"RedisMessageBus(url={self._url!r})"
