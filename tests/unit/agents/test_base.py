"""Unit tests for SpecialistAgent base class and EchoAgent."""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from lustre.agents.base import AgentConfig, SpecialistAgent
from lustre.agents.echo_agent import CodeEchoAgent, EchoAgent
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus() -> MemoryMessageBus:
    return MemoryMessageBus()


@pytest.fixture
def echo_config() -> AgentConfig:
    return AgentConfig(name="echo", description="test echo agent")


# ---------------------------------------------------------------------------
# SpecialistAgent — lifecycle
# ---------------------------------------------------------------------------

def test_agent_start_stop(echo_config: AgentConfig, bus: MemoryMessageBus) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)

    assert not agent.is_running
    agent.start()
    assert agent.is_running
    agent.stop()
    assert not agent.is_running


def test_agent_double_start_no_crash(echo_config: AgentConfig, bus: MemoryMessageBus) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)
    agent.start()
    agent.start()  # should not raise
    assert agent.is_running
    agent.stop()


def test_agent_stop_when_not_started(echo_config: AgentConfig, bus: MemoryMessageBus) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)
    agent.stop()  # should not raise
    assert not agent.is_running


# ---------------------------------------------------------------------------
# SpecialistAgent — message handling
# ---------------------------------------------------------------------------

def test_agent_receives_task_and_replies(
    echo_config: AgentConfig, bus: MemoryMessageBus
) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)
    agent.start()

    task_id = f"t-{uuid.uuid4().hex[:6]}"
    conversation_id = f"c-{uuid.uuid4().hex[:6]}"
    request = TaskRequest(
        task_id=task_id,
        description="say hello",
        context={},
    )

    results: list[Message] = []
    bus.subscribe(f"result.{agent.name}", results.append)

    bus.publish(
        f"task.{agent.name}",
        Message(
            sender="supervisor",
            type=MessageType.TASK_REQUEST,
            payload=request.to_dict(),
            conversation_id=conversation_id,
        ),
    )

    # Wait for reply
    for _ in range(50):
        if results:
            break
        time.sleep(0.05)

    assert len(results) == 1
    assert results[0].sender == agent.name
    assert results[0].payload["task_id"] == task_id
    assert results[0].payload["status"] == "completed"
    assert "say hello" in results[0].payload["output"]

    agent.stop()


def test_agent_ignores_messages_when_stopped(
    echo_config: AgentConfig, bus: MemoryMessageBus
) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)
    agent.start()
    agent.stop()

    results: list[Message] = []
    bus.subscribe(f"result.{agent.name}", results.append)

    bus.publish(
        f"task.{agent.name}",
        Message(
            sender="supervisor",
            type=MessageType.TASK_REQUEST,
            payload=TaskRequest(task_id="t1", description="test").to_dict(),
            conversation_id="c1",
        ),
    )

    time.sleep(0.2)
    assert len(results) == 0


def test_agent_reply_has_reply_to_set(
    echo_config: AgentConfig, bus: MemoryMessageBus
) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)
    agent.start()

    results: list[Message] = []
    bus.subscribe(f"result.{agent.name}", results.append)

    bus.publish(
        f"task.{agent.name}",
        Message(
            id="msg-123",
            sender="supervisor",
            type=MessageType.TASK_REQUEST,
            payload=TaskRequest(task_id="t1", description="test").to_dict(),
            conversation_id="c1",
        ),
    )

    for _ in range(50):
        if results:
            break
        time.sleep(0.05)

    assert len(results) == 1
    assert results[0].reply_to == "msg-123"

    agent.stop()


# ---------------------------------------------------------------------------
# EchoAgent
# ---------------------------------------------------------------------------

def test_echo_agent_returns_completed(echo_config: AgentConfig, bus: MemoryMessageBus) -> None:
    agent = EchoAgent(config=echo_config, bus=bus)
    result = agent.process_task(TaskRequest(task_id="t1", description="do stuff"))
    assert result.status == "completed"
    assert "do stuff" in result.output


def test_code_echo_agent_name_is_code(bus: MemoryMessageBus) -> None:
    agent = CodeEchoAgent(bus=bus)
    assert agent.name == "code"
    assert agent.config.description == "Simulated code agent (no real LLM)"


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------

def test_agent_config_defaults() -> None:
    config = AgentConfig(name="test")
    assert config.description == ""
    assert config.skills == []
    assert config.model_provider is None


# ---------------------------------------------------------------------------
# SpecialistAgent — error handling
# ---------------------------------------------------------------------------

class FailingAgent(SpecialistAgent):
    """Agent that always raises during process_task."""

    def process_task(self, task: TaskRequest) -> TaskResult:
        raise RuntimeError("intentional failure")


def test_agent_catches_process_exception(
    echo_config: AgentConfig, bus: MemoryMessageBus
) -> None:
    # Replace with a failing agent
    failing_config = AgentConfig(name=echo_config.name, description="failing")
    agent = FailingAgent(config=failing_config, bus=bus)
    agent.start()

    results: list[Message] = []
    bus.subscribe(f"result.{agent.name}", results.append)

    bus.publish(
        f"task.{agent.name}",
        Message(
            sender="supervisor",
            type=MessageType.TASK_REQUEST,
            payload=TaskRequest(task_id="t1", description="fail me").to_dict(),
            conversation_id="c1",
        ),
    )

    for _ in range(50):
        if results:
            break
        time.sleep(0.05)

    assert len(results) == 1
    assert results[0].payload["status"] == "failed"
    assert "intentional failure" in results[0].payload["error"]

    agent.stop()
