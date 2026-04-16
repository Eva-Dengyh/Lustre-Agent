"""Central tool registry for Lustre Agent.

Provides:
- @register_tool decorator for declaring tools
- ToolRegistry class (singleton) for managing registered tools
- Per-agent tool enable/disable lists
- Tool schema generation for LLM consumption
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["ToolRegistry", "register_tool", "get_tool_registry", "ToolDef"]


# ---------------------------------------------------------------------------
# ToolDef — lightweight tool descriptor (used in models/executor.py)
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    """A callable tool with schema metadata.

    In Lustre, ToolDef is the canonical tool representation used by
    ReActExecutor.  This mirrors the shape expected by the LLM:
    - name / description / parameters (JSON Schema)
    - function(args: dict, task_id: str | None) -> str
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the tool's arguments
    function: Callable[[dict[str, Any], str | None], str] = field(repr=False)
    # Internal
    owner: str = "builtin"   # "builtin" | "skill:<name>" | "plugin:<name>"
    enabled: bool = True

    def invoke(self, args: dict[str, Any], task_id: str | None = None) -> str:
        """Call the tool function with given arguments."""
        return self.function(args, task_id)

    def to_schema(self) -> dict[str, Any]:
        """Return the JSON Schema representation for the LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the global ToolRegistry singleton."""
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is None:
        _TOOL_REGISTRY = ToolRegistry()
    return _TOOL_REGISTRY


# ---------------------------------------------------------------------------
# register_tool decorator
# ---------------------------------------------------------------------------

def register_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    owner: str = "builtin",
    enabled: bool = True,
) -> Callable[[Callable], Callable]:
    """Decorator to register a tool function with the global registry.

    Usage:
        @register_tool(
            name="my_tool",
            description="Does something useful",
            parameters={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
        )
        def my_tool(args: dict, task_id: str | None) -> str:
            return f"Did: {args['arg']}"

    The decorated function is wrapped to satisfy the ToolDef interface.
    """

    def decorator(fn: Callable) -> Callable:
        tool_def = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            function=fn,
            owner=owner,
            enabled=enabled,
        )
        registry = get_tool_registry()
        registry.register(tool_def)
        logger.debug("Registered tool: %s (owner=%s)", name, owner)
        return fn  # return the original function (not wrapped)

    return decorator


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Central registry for all available tools.

    Tools are registered via @register_tool or directly via register().
    Agents query tools by name or get all tools they are allowed to use.

    Singleton: use get_tool_registry() to get the instance.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool_def: ToolDef) -> None:
        """Register a ToolDef. Overwrites existing tool with same name."""
        self._tools[tool_def.name] = tool_def
        logger.debug("Tool registered: %s", tool_def.name)

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)

    def is_registered(self, name: str) -> bool:
        """Return True if a tool with this name is registered."""
        return name in self._tools

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, name: str) -> ToolDef | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def all_tools(self) -> list[ToolDef]:
        """Return all registered tools (including disabled)."""
        return list(self._tools.values())

    def enabled_tools(self) -> list[ToolDef]:
        """Return only enabled tools."""
        return [t for t in self._tools.values() if t.enabled]

    def get_tools(
        self,
        names: list[str] | None = None,
        owner: str | None = None,
    ) -> list[ToolDef]:
        """Get tools by name list, or filter by owner, or all enabled.

        Args:
            names: if provided, return only tools with these names
            owner: if provided, return only tools with this owner tag
            if neither: return all enabled tools
        """
        candidates = self.enabled_tools()

        if names is not None:
            candidates = [t for t in candidates if t.name in names]

        if owner is not None:
            candidates = [t for t in candidates if t.owner == owner]

        return candidates

    def names(self) -> list[str]:
        """Return sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    # ------------------------------------------------------------------
    # Per-agent enable/disable
    # ------------------------------------------------------------------

    def enable_tool(self, name: str) -> None:
        """Enable a specific tool."""
        tool = self._tools.get(name)
        if tool:
            tool.enabled = True

    def disable_tool(self, name: str) -> None:
        """Disable a specific tool globally."""
        tool = self._tools.get(name)
        if tool:
            tool.enabled = False
            logger.info("Tool disabled globally: %s", name)

    # ------------------------------------------------------------------
    # Schema export
    # ------------------------------------------------------------------

    def get_schemas(self, tool_names: list[str] | None = None) -> list[dict]:
        """Return JSON Schema list for all enabled tools (or named subset)."""
        tools = self.get_tools(names=tool_names)
        return [t.to_schema() for t in tools]

    def __repr__(self) -> str:
        enabled = len(self.enabled_tools())
        total = len(self._tools)
        return f"ToolRegistry({enabled}/{total} tools enabled)"
