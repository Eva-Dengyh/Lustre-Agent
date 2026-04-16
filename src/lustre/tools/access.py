"""Per-agent tool access control.

Allows fine-grained control over which agents can use which tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lustre.tools.registry import ToolDef, get_tool_registry

if TYPE_CHECKING:
    pass

__all__ = ["get_tools_for_agent", "AgentToolPolicy"]


# ---------------------------------------------------------------------------
# Default policy
# ---------------------------------------------------------------------------

# All known agents and their allowed tools (None = all enabled tools)
DEFAULT_POLICY: dict[str, list[str] | None] = {
    # CodeAgent: full access to all tools
    "code": None,   # all enabled tools
    # ResearchAgent: read + search only (no write/patch/terminal)
    "research": ["read_file", "search_files"],
    # TestAgent: terminal + read + search (can run tests, no write)
    "test": ["read_file", "search_files", "terminal"],
}


class AgentToolPolicy:
    """Controls which tools each agent is allowed to use.

    Usage:
        policy = AgentToolPolicy()
        tools = policy.get_tools_for_agent("code")
        # returns all enabled tools for code agent
    """

    def __init__(
        self,
        overrides: dict[str, list[str] | None] | None = None,
    ) -> None:
        # Merge default policy with overrides
        self._policy = dict(DEFAULT_POLICY)
        if overrides:
            self._policy.update(overrides)

    def get_tools_for_agent(
        self,
        agent_name: str,
        *,
        allowlist: list[str] | None = None,
        denylist: list[str] | None = None,
    ) -> list[ToolDef]:
        """Return the list of tools the given agent may use.

        Resolution order:
            1. If policy says None → all enabled tools (minus denylist)
            2. If policy has explicit list → that list (minus denylist)
            3. allowlist overrides policy

        Args:
            agent_name: name of the agent
            allowlist: if provided, only these tools (after denylist)
            denylist: always exclude these tools
        """
        registry = get_tool_registry()

        # Determine base tool names
        if allowlist is not None:
            tool_names = allowlist
        else:
            tool_names = self._policy.get(agent_name)

        if tool_names is None:
            # None = all enabled tools
            candidates = registry.enabled_tools()
        else:
            candidates = registry.get_tools(names=tool_names)

        # Apply denylist
        if denylist:
            candidates = [t for t in candidates if t.name not in denylist]

        return candidates

    def set_policy(self, agent_name: str, tool_names: list[str] | None) -> None:
        """Set or update the policy for an agent.

        tool_names=None means the agent can use all enabled tools.
        """
        self._policy[agent_name] = tool_names

    def get_policy(self, agent_name: str) -> list[str] | None:
        """Return the configured tool list for an agent (may be None=all)."""
        return self._policy.get(agent_name)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def get_tools_for_agent(
    agent_name: str,
    **kwargs,
) -> list[ToolDef]:
    """Convenience wrapper around AgentToolPolicy().get_tools_for_agent()."""
    return AgentToolPolicy().get_tools_for_agent(agent_name, **kwargs)
