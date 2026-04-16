"""ReAct executor — handles the Reason + Act + Observe loop.

The executor drives a single task to completion by alternating between:
1. Reason: ask the LLM what to do next (with tools available)
2. Act: run the chosen tool and collect the result
3. Observe: feed the result back to the LLM
Loop until the LLM returns a final answer (no more tool calls).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from lustre.models.client import ChatMessage, ModelClient
from lustre.tools.registry import ToolDef

__all__ = ["ReActExecutor", "ToolResult"]


logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Tool abstraction
# -----------------------------------------------------------------------------

@dataclass
class ToolResult:
    """Result of a single tool call."""

    tool_name: str
    raw: Any  # provider-specific raw result
    error: str | None = None

    @property
    def content(self) -> str:
        """Human-readable string representation of the result."""
        if self.error:
            return f"Error: {self.error}"
        if isinstance(self.raw, str):
            return self.raw
        try:
            return json.dumps(self.raw, indent=2, ensure_ascii=False)
        except Exception:
            return str(self.raw)


# ---------------------------------------------------------------------------
# ReAct Executor
# ---------------------------------------------------------------------------

@dataclass
class ExecutionTrace:
    """Records each step of the ReAct loop for debugging/audit."""

    steps: list[dict[str, Any]] = field(default_factory=list)

    def add_reasoning(self, thought: str) -> None:
        self.steps.append({"type": "reasoning", "text": thought})

    def add_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self.steps.append({"type": "tool_call", "tool": name, "arguments": arguments})

    def add_observation(self, tool_name: str, result: str, error: str | None = None) -> None:
        self.steps.append({
            "type": "observation",
            "tool": tool_name,
            "result": result[:500] if result else "",
            "error": error,
        })

    def add_final_answer(self, text: str) -> None:
        self.steps.append({"type": "final_answer", "text": text})


class ReActExecutor:
    """Runs a ReAct loop until the model returns a final answer."""

    def __init__(
        self,
        client: ModelClient,
        system_prompt: str,
        tools: list[ToolDef],
        max_iterations: int = 20,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools
        self.max_iterations = max_iterations
        self.model = model
        self.temperature = temperature
        self.trace = ExecutionTrace()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        task: str,
        *,
        conversation_history: list[ChatMessage] | None = None,
        task_id: str | None = None,
    ) -> tuple[str, ExecutionTrace]:
        """Run the ReAct loop for the given task.

        Returns:
            (final_answer, trace) — final_answer is the model's last text response.
        """
        self.trace = ExecutionTrace()

        # Build the initial message list
        messages: list[ChatMessage] = []
        if conversation_history:
            messages.extend(conversation_history)

        # Inject system prompt
        messages.append(ChatMessage(role="system", content=self.system_prompt))
        messages.append(ChatMessage(role="user", content=task))

        # Convert tool defs to provider schema
        tool_schemas = [self._tool_to_schema(t) for t in self.tools]
        tool_map: dict[str, ToolDef] = {t.name: t for t in self.tools}

        # ReAct loop
        for iteration in range(self.max_iterations):
            logger.debug("ReAct iteration %d/%d", iteration + 1, self.max_iterations)

            # Ask the model
            response = self.client.chat(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                tools=tool_schemas if tool_schemas else None,
            )

            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            # Record reasoning (the text content between tool calls)
            if content:
                self.trace.add_reasoning(content)
                messages.append(ChatMessage(role="assistant", content=content))

            if not tool_calls:
                # No more tool calls — this is the final answer
                self.trace.add_final_answer(content)
                return content, self.trace

            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                arguments = tc.get("arguments", {})

                self.trace.add_tool_call(tool_name, arguments)

                if tool_name not in tool_map:
                    result = ToolResult(
                        tool_name=tool_name,
                        raw=None,
                        error=f"Unknown tool: {tool_name}",
                    )
                else:
                    tool_def = tool_map[tool_name]
                    try:
                        raw = tool_def.invoke(arguments, task_id=task_id)
                        result = ToolResult(tool_name=tool_name, raw=raw)
                    except Exception as exc:  # noqa: BLE001
                        result = ToolResult(
                            tool_name=tool_name,
                            raw=None,
                            error=str(exc),
                        )

                self.trace.add_observation(
                    tool_name,
                    result.content,
                    error=result.error,
                )

                # Append tool result as a tool message
                messages.append(ChatMessage(
                    role="tool",
                    content=result.content,
                    tool_call_id=tc.get("id"),
                    name=tool_name,
                ))

        # Exceeded max iterations
        final = (
            f"[停止] 达到最大迭代次数 ({self.max_iterations})。"
            f"以下是目前的进展:\n{self._summarise_trace()}"
        )
        self.trace.add_final_answer(final)
        return final, self.trace

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_to_schema(tool: ToolDef) -> dict[str, Any]:
        """Convert a ToolDef to the provider's tool schema format."""
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }

    def _summarise_trace(self) -> str:
        """Build a summary of what has been done so far."""
        parts = []
        for step in self.trace.steps:
            t = step["type"]
            if t == "tool_call":
                parts.append(f"- 调用了工具: {step['tool']}")
            elif t == "observation":
                if step.get("error"):
                    parts.append(f"- {step['tool']} 出错: {step['error'][:100]}")
                else:
                    parts.append(f"- {step['tool']} 返回: {step['result'][:150]}")
        return "\n".join(parts) if parts else "(无)"
