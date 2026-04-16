"""Tool system — registry, decorators, access control, and built-in tools."""

from lustre.tools.registry import (
    ToolRegistry,
    register_tool,
    get_tool_registry,
    ToolDef,
)

# Import builtins to trigger @register_tool decorators
from lustre.tools import builtin  # noqa: F401

from lustre.tools.access import AgentToolPolicy, get_tools_for_agent

# Public getters
def get_all_tools() -> list[ToolDef]:
    return get_tool_registry().enabled_tools()

__all__ = [
    "ToolRegistry",
    "register_tool",
    "get_tool_registry",
    "ToolDef",
    "get_all_tools",
    "AgentToolPolicy",
    "get_tools_for_agent",
]
