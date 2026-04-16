"""Unit tests for MemoryMessageBus."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from lustre.bus.base import MessageBus
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus() -> MemoryMessageBus:
    """Fresh bus for each test."""
    return MemoryMessageBus(max_hops=10)


@pytest.fixture
def sample_message() -> Message:
    return Message(
        sender="supervisor",
        recipient="code",
        type=MessageType.TASK_REQUEST,
        payload={"task_id": "t1", "description": "write hello"},
        conversation_id="c1",
        timestamp=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Tests — publish / subscribe
# ---------------------------------------------------------------------------

def test_publish_delivers_to_subscriber(bus: MemoryMessageBus, sample_message: Message) -> None:
    received: list[Message] = []

    bus.subscribe("task.code", received.append)
    bus.publish("task.code", sample_message)

    assert len(received) == 1
    assert received[0].id == sample_message.id
    assert received[0].sender == "supervisor"


def test_publish_to_multiple_subscribers(bus: MemoryMessageBus, sample_message: Message) -> None:
    received1: list[Message] = []
    received2: list[Message] = []

    bus.subscribe("task.code", received1.append)
    bus.subscribe("task.code", received2.append)
    bus.publish("task.code", sample_message)

    assert len(received1) == 1
    assert len(received2) == 1


def test_publish_to_wrong_topic(bus: MemoryMessageBus, sample_message: Message) -> None:
    received: list[Message] = []
    bus.subscribe("task.code", received.append)
    bus.publish("task.research", sample_message)
    assert len(received) == 0


def test_broadcast_wildcard(bus: MemoryMessageBus, sample_message: Message) -> None:
    received: list[Message] = []
    bus.subscribe("*", received.append)
    bus.publish("anything.at.all", sample_message)
    assert len(received) == 1


def test_unsubscribe_stops_delivery(bus: MemoryMessageBus, sample_message: Message) -> None:
    received: list[Message] = []
    sub = bus.subscribe("task.code", received.append)
    bus.unsubscribe(sub)
    bus.publish("task.code", sample_message)
    assert len(received) == 0


def test_list_topics(bus: MemoryMessageBus, sample_message: Message) -> None:
    bus.subscribe("task.code", lambda m: None)
    bus.subscribe("task.test", lambda m: None)
    topics = bus.list_topics()
    assert "task.code" in topics
    assert "task.test" in topics


# ---------------------------------------------------------------------------
# Tests — Message data class
# ---------------------------------------------------------------------------

def test_message_increment_hops(sample_message: Message) -> None:
    assert sample_message.hops == 0
    new_msg = sample_message.increment_hops()
    assert new_msg.hops == 1
    assert new_msg.id == sample_message.id
    assert sample_message.hops == 0  # original unchanged


def test_message_to_dict_roundtrip(sample_message: Message) -> None:
    d = sample_message.to_dict()
    restored = Message.from_dict(d)
    assert restored.id == sample_message.id
    assert restored.sender == sample_message.sender
    assert restored.type == sample_message.type


def test_message_from_dict_with_string_type() -> None:
    d = {
        "id": "x",
        "sender": "s",
        "type": "task_request",
        "payload": {},
        "conversation_id": "c",
        "timestamp": datetime.now().isoformat(),
    }
    msg = Message.from_dict(d)
    assert msg.type == MessageType.TASK_REQUEST


# ---------------------------------------------------------------------------
# Tests — TaskRequest / TaskResult
# ---------------------------------------------------------------------------

def test_task_request_to_dict() -> None:
    req = TaskRequest(
        task_id="t1",
        description="write a function",
        context={"lang": "python"},
        skills_requested=["python-best-practices"],
    )
    d = req.to_dict()
    assert d["task_id"] == "t1"
    assert d["skills_requested"] == ["python-best-practices"]


def test_task_result_to_dict() -> None:
    res = TaskResult(
        task_id="t1",
        status="completed",
        output="def hello(): pass",
        artifacts={"hello.py": "def hello(): pass"},
        agent_name="code",
    )
    d = res.to_dict()
    assert d["status"] == "completed"
    assert d["artifacts"]["hello.py"] == "def hello(): pass"


# ---------------------------------------------------------------------------
# Tests — max hops / loop detection
# ---------------------------------------------------------------------------

def test_max_hops_discard(bus: MemoryMessageBus) -> None:
    received: list[Message] = []
    bus.subscribe("task.code", received.append)
    bus.publish("task.code", Message(
        sender="x",
        type=MessageType.TASK_REQUEST,
        payload={},
        conversation_id="c",
        hops=10,  # already at max
    ))
    assert len(received) == 0


def test_increment_hops_near_limit(bus: MemoryMessageBus) -> None:
    received: list[Message] = []
    bus.subscribe("task.code", received.append)
    msg = Message(sender="x", type=MessageType.TASK_REQUEST, payload={}, conversation_id="c", hops=9)
    bus.publish("task.code", msg.increment_hops())  # hops becomes 10
    assert len(received) == 0


# ---------------------------------------------------------------------------
# Tests — concurrent publish
# ---------------------------------------------------------------------------

def test_concurrent_publish(bus: MemoryMessageBus) -> None:
    received: list[Message] = []
    bus.subscribe("task.code", received.append)

    def _publish() -> None:
        for _ in range(100):
            bus.publish("task.code", Message(
                sender="supervisor",
                type=MessageType.TASK_REQUEST,
                payload={},
                conversation_id="c",
            ))

    threads = [threading.Thread(target=_publish) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(received) == 400


# ---------------------------------------------------------------------------
# Tests — error handling in callback
# ---------------------------------------------------------------------------

def test_callback_exception_does_not_crash_bus(bus: MemoryMessageBus, sample_message: Message) -> None:
    bad_received: list[Message] = []
    good_received: list[Message] = []

    def bad_cb(msg: Message) -> None:
        bad_received.append(msg)
        raise RuntimeError("boom")

    bus.subscribe("task.code", bad_cb)
    bus.subscribe("task.code", good_received.append)
    # Should not raise
    bus.publish("task.code", sample_message)

    assert len(bad_received) == 1
    assert len(good_received) == 1  # good callback still called


# ---------------------------------------------------------------------------
# Tests — request / response
# ---------------------------------------------------------------------------

def test_request_response_success(bus: MemoryMessageBus) -> None:
    def code_agent_reply(msg: Message) -> None:
        bus.publish("result.supervisor", Message(
            sender="code",
            type=MessageType.TASK_RESULT,
            payload={"task_id": msg.payload["task_id"], "status": "completed"},
            conversation_id=msg.conversation_id,
            reply_to=msg.id,
        ))

    bus.subscribe("task.code", code_agent_reply)

    request_msg = Message(
        sender="supervisor",
        type=MessageType.TASK_REQUEST,
        payload={"task_id": "t1", "description": "hello"},
        conversation_id="c",
    )
    reply = bus.request("task.code", request_msg, timeout=5.0)

    assert reply.sender == "code"
    assert reply.payload["status"] == "completed"
    assert reply.reply_to == request_msg.id


def test_request_timeout(bus: MemoryMessageBus) -> None:
    # No one is listening
    request_msg = Message(
        sender="supervisor",
        type=MessageType.TASK_REQUEST,
        payload={"task_id": "t1"},
        conversation_id="c",
    )
    with pytest.raises(TimeoutError):
        bus.request("task.nonexistent", request_msg, timeout=0.5)
