"""EchoAgent — a mock specialist that echoes back a description.

Used during Phase 2-3 to verify the message bus and agent lifecycle
without requiring actual LLM API calls.  Replaces a real specialist
(e.g. CodeAgent) during integration testing.

Usage:
    from lustre.bus.memory_bus import MemoryMessageBus
    from lustre.agents.echo_agent import EchoAgent

    bus = MemoryMessageBus()
    agent = EchoAgent(name="echo", bus=bus)
    agent.start()

    # Send a task via bus...
    # agent will reply on result.echo
"""

from __future__ import annotations

from lustre.agents.base import AgentConfig, SpecialistAgent
from lustre.bus.message import TaskRequest, TaskResult


class EchoAgent(SpecialistAgent):
    """A mock agent that simulates work and returns a fixed response.

    Always responds with status="completed" after a short simulated delay.
    The output contains the task description for easy verification.
    """

    def process_task(self, task: TaskRequest) -> TaskResult:
        """Echo back the task description as output."""
        return TaskResult(
            task_id=task.task_id,
            status="completed",
            output=f"[EchoAgent] Received: {task.description}",
            artifacts={},
            agent_name=self.name,
        )


class CodeEchoAgent(EchoAgent):
    """EchoAgent configured to look like a Code agent for CLI demos."""

    def __init__(self, bus: MessageBus) -> None:  # type: ignore[override]
        super().__init__(
            config=AgentConfig(
                name="code",
                description="Simulated code agent (no real LLM)",
                skills=["python-best-practices"],
            ),
            bus=bus,
        )
