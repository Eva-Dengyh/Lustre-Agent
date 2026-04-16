"""Specialist agents — code, test, research."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lustre.agents.base import AgentConfig, SpecialistAgent
from lustre.agents.echo_agent import CodeEchoAgent, EchoAgent

if TYPE_CHECKING:
    from lustre.bus.base import MessageBus

__all__ = [
    "SpecialistAgent",
    "AgentConfig",
    "EchoAgent",
    "CodeEchoAgent",
]


class ResearchEchoAgent(EchoAgent):
    """EchoAgent configured to look like a Research agent."""

    def __init__(self, bus: "MessageBus") -> None:
        super().__init__(
            config=AgentConfig(
                name="research",
                description="Simulated research agent (no real LLM)",
                skills=[],
            ),
            bus=bus,
        )


class TestEchoAgent(EchoAgent):
    """EchoAgent configured to look like a Test agent."""

    def __init__(self, bus: "MessageBus") -> None:
        super().__init__(
            config=AgentConfig(
                name="test",
                description="Simulated test agent (no real LLM)",
                skills=[],
            ),
            bus=bus,
        )


# Registry of available specialist agent classes.
# Keys are agent names used in config and message topics.
SPECIALIST_AGENTS: dict[str, type[SpecialistAgent]] = {
    "code": CodeEchoAgent,
    "research": ResearchEchoAgent,
    "test": TestEchoAgent,
}
