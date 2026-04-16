"""Unified LLM client with provider abstraction.

Phase 4: supports Anthropic (Claude) and OpenAI.
Phase 5+ will add DeepSeek, Gemini, etc.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ModelClient", "AnthropicClient", "OpenAIClient", "ChatMessage"]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    """A single message in a chat conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None  # for tool messages
    tool_call_id: str | None = None  # for tool messages


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class ModelClient(ABC):
    """Abstract LLM client — all providers implement this interface."""

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a chat completion request.

        Returns the raw provider response dict (standardised across providers).
        Provider-specific response fields are normalised to these keys:
          - `content`: str — the text response
          - `tool_calls`: list[dict] — each with `id`, `name`, `arguments` (json str)
          - `stop_reason`: str — why the model stopped
          - `usage`: dict — `input_tokens`, `output_tokens`, `total_tokens`
        """
        ...


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

class AnthropicClient(ModelClient):
    """Anthropic Claude client using the official SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = anthropic.Anthropic(api_key=self._api_key)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Separate system message
        system_parts: list[str] = []
        non_system: list[ChatMessage] = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                non_system.append(msg)

        system = "\n".join(system_parts) if system_parts else None

        # Build Anthropic-format content blocks
        content_blocks: list[str | dict] = []
        for msg in non_system:
            if msg.role == "user":
                content_blocks.append({"type": "text", "text": msg.content})
            elif msg.role == "assistant":
                # May contain text + tool_calls
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                # tool_calls handled separately below
            elif msg.role == "tool":
                content_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                })

        # Add tool_calls to the last assistant message if present
        extra_kwargs: dict[str, Any] = {}
        if tools:
            extra_kwargs["tools"] = tools
        if tool_choice:
            extra_kwargs["tool_choice"] = tool_choice

        # Flatten content_blocks: group consecutive text blocks
        # Anthropic accepts a list of content blocks
        response = self._client.messages.create(
            model=model or "claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": msg.role, "content": msg.content} for msg in non_system],
            temperature=temperature,
            **extra_kwargs,
            **kwargs,
        )

        # Normalise response
        result_content = ""
        tool_calls: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                result_content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,  # dict, not JSON string
                })

        return {
            "content": result_content,
            "tool_calls": tool_calls,
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            },
        }


# ---------------------------------------------------------------------------
# OpenAI (GPT-4o, o3, etc.)
# ---------------------------------------------------------------------------

class OpenAIClient(ModelClient):
    """OpenAI client using the official SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        import openai
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = openai.OpenAI(api_key=self._api_key)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Build OpenAI-format messages
        openai_messages: list[dict[str, Any]] = []
        for msg in messages:
            m: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                m["name"] = msg.name
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            openai_messages.append(m)

        extra_kwargs: dict[str, Any] = {}
        if tools:
            extra_kwargs["tools"] = tools
        if tool_choice:
            extra_kwargs["tool_choice"] = tool_choice

        response = self._client.chat.completions.create(
            model=model or "gpt-4o",
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra_kwargs,
            **kwargs,
        )

        choice = response.choices[0]
        message = choice.message

        # Collect tool calls
        tool_calls: list[dict[str, Any]] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args_str = tc.function.arguments
                import json as _json
                args = _json.loads(args_str) if isinstance(args_str, str) else args_str
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": args,
                })

        return {
            "content": message.content or "",
            "tool_calls": tool_calls,
            "stop_reason": choice.finish_reason,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def create_client(
    provider: Literal["anthropic", "openai"],
    api_key: str | None = None,
) -> ModelClient:
    """Factory: create a ModelClient for the given provider."""
    if provider == "anthropic":
        return AnthropicClient(api_key=api_key)
    if provider == "openai":
        return OpenAIClient(api_key=api_key)
    raise ValueError(f"Unknown provider: {provider!r}")
