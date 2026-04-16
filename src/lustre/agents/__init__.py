"""Specialist agents — code, test, research."""

from lustre.agents.base import AgentConfig, SpecialistAgent
from lustre.agents.echo_agent import CodeEchoAgent, EchoAgent

__all__ = [
    "SpecialistAgent",
    "AgentConfig",
    "EchoAgent",
    "CodeEchoAgent",
]

# Registry of available specialist agent classes.
# Keys are agent names used in config and message topics.
# Values are subclasses of SpecialistAgent.
SPECIALIST_AGENTS: dict[str, type[SpecialistAgent]] = {
    "code": CodeEchoAgent,
    "test": CodeEchoAgent,
    "research": CodeEchoAgent,
}
