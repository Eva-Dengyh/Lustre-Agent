"""Unified LLM client with provider abstraction.

Phase 4: supports Anthropic (Claude) and OpenAI.
Phase 5+ will add DeepSeek, Gemini, etc.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ModelClient", "AnthropicClient", "OpenAIClient", "MiniMaxClient", "ClaudeCodeClient", "ChatMessage"]


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
# MiniMax (OpenAI-compatible API)
# ---------------------------------------------------------------------------

class MiniMaxClient(ModelClient):
    """MiniMax client using the OpenAI-compatible API.

    MiniMax's API is compatible with OpenAI's chat completions format.
    Base URL: https://api.minimax.chat/v1
    Model names vary: e.g. MiniMax-Text-01, MiniMax-Video-01

    API key format: Bearer token from MiniMax console.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimax.chat/v1",
        model: str = "MiniMax-Text-01",
    ) -> None:
        import openai

        self._api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self._model = model
        self._client = openai.OpenAI(
            api_key=self._api_key,
            base_url=base_url,
        )

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
            model=model or self._model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra_kwargs,
            **kwargs,
        )

        choice = response.choices[0]
        message = choice.message

        tool_calls: list[dict[str, Any]] = []
        if message.tool_calls:
            import json as _json

            for tc in message.tool_calls:
                args = (
                    _json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else tc.function.arguments
                )
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
# Claude Code (subprocess ACP protocol)
# ---------------------------------------------------------------------------

class ClaudeCodeClient(ModelClient):
    """Claude Code CLI — subprocess adapter using the ACP (Agent Communication Protocol).

    This does NOT use an API. Instead it spawns `claude --acp --stdio` as a
    subprocess and communicates with it over stdio using JSON messages.

    Requirements:
        - Claude Code CLI installed: `npm install -g @anthropic-ai/claude-code`
        - ANTHROPIC_API_KEY set in environment (Claude Code uses it directly)

    This client is suitable when you want Claude Code to handle the full
    ReAct loop (tool execution, file operations, git, etc.) as a sub-agent,
    while the Lustre Supervisor coordinates multiple such agents.

    Usage:
        client = ClaudeCodeClient()
        result = client.chat([ChatMessage(role="user", content="...")])
    """

    def __init__(
        self,
        claude_path: str = "claude",
        model: str = "claude-sonnet-4-6",
        **kwargs: Any,
    ) -> None:
        import json as _json
        import subprocess
        import threading

        self._claude_path = claude_path
        self._model = model
        self._json = _json
        self._subprocess = subprocess
        self._threading = threading

        # Lazy — process started on first chat() call
        self._proc = None
        self._proc_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._pending: dict[str, tuple[threading.Event, dict]] = {}
        self._pending_lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def _start(self) -> None:
        """Start the claude --acp --stdio subprocess."""
        with self._proc_lock:
            if self._proc is not None:
                return

            self._proc = self._subprocess.Popen(
                [self._claude_path, "--acp", "--stdio"],
                stdin=self._subprocess.PIPE,
                stdout=self._subprocess.PIPE,
                stderr=self._subprocess.DEVNULL,
                text=False,  # binary mode for JSON
                bufsize=1,
            )
            # Start reader thread
            self._reader_thread = self._threading.Thread(
                target=self._read_loop,
                name="claude-acp-reader",
                daemon=True,
            )
            self._reader_thread.start()

    def _read_loop(self) -> None:
        """Background thread: reads JSON messages from claude stdout."""
        assert self._proc is not None
        stream = self._proc.stdout
        assert stream is not None

        while True:
            try:
                line = stream.readline()
                if not line:
                    break
                msg = self._json.loads(line.decode("utf-8"))
                self._dispatch(msg)
            except Exception:
                break

    def _dispatch(self, msg: dict) -> None:
        """Route an incoming ACP message to its pending request."""
        with self._pending_lock:
            msg_type = msg.get("type", "")
            req_id = msg.get("request_id", "")
            if req_id in self._pending:
                ev, holder = self._pending.pop(req_id)
                holder["msg"] = msg
                ev.set()

    def _close(self) -> None:
        with self._proc_lock:
            if self._proc is None:
                return
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
            self._proc = None

    # -------------------------------------------------------------------------
    # ModelClient interface
    # -------------------------------------------------------------------------

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
        """Send a conversation to Claude Code via ACP, return the response.

        ACP protocol:
            1. Send {"type": "session", "model": "...", ...}
            2. Send {"type": "user", "content": "...", "request_id": "..."}
            3. Read responses {"type": "assistant", "content": "...", ...}
            4. Read done {"type": "done", ...}
        """
        import uuid

        self._start()

        # Build ACP messages from our ChatMessage list
        acp_messages: list[dict[str, Any]] = []
        for msg in messages:
            role_map = {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"}
            m = {"type": "message", "role": role_map.get(msg.role, msg.role), "content": msg.content}
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.name:
                m["name"] = msg.name
            acp_messages.append(m)

        # Send session init
        session_msg = {
            "type": "session",
            "model": model or self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            session_msg["tools"] = tools
        self._send(session_msg)

        # Send conversation
        result_parts: list[str] = []
        result_tool_calls: list[dict[str, Any]] = []
        all_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        for acp_msg in acp_messages:
            req_id = str(uuid.uuid4())
            event = self._threading.Event()
            with self._pending_lock:
                self._pending[req_id] = (event, {})

            self._send({**acp_msg, "type": "user", "request_id": req_id})

            # Collect responses for this user message until next user msg or done
            while True:
                if not event.wait(timeout=60):
                    raise TimeoutError(f"Claude Code request {req_id} timed out")

                with self._pending_lock:
                    _, holder = self._pending.get(req_id, (None, {}))
                    resp = holder.get("msg", {})

                resp_type = resp.get("type", "")
                if resp_type == "assistant":
                    if resp.get("content"):
                        result_parts.append(resp["content"])
                elif resp_type == "tool_call":
                    args = resp.get("arguments", {})
                    if isinstance(args, str):
                        import json as _json

                        args = _json.loads(args)
                    result_tool_calls.append({
                        "id": resp.get("id", ""),
                        "name": resp.get("name", ""),
                        "arguments": args,
                    })
                elif resp_type == "done":
                    usage = resp.get("usage", {})
                    if usage:
                        all_usage["input_tokens"] += usage.get("input_tokens", 0)
                        all_usage["output_tokens"] += usage.get("output_tokens", 0)
                    break
                elif resp_type == "error":
                    raise RuntimeError(f"Claude Code error: {resp.get('error')}")
                elif resp_type == "result":
                    # Final result message
                    if resp.get("content"):
                        result_parts.append(resp["content"])
                    break

        return {
            "content": "\n".join(result_parts),
            "tool_calls": result_tool_calls,
            "stop_reason": "end_turn",
            "usage": all_usage,
        }

    def _send(self, msg: dict) -> None:
        """Send a JSON message to claude stdin."""
        assert self._proc is not None
        data = self._json.dumps(msg).encode("utf-8") + b"\n"
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except BrokenPipeError:
            self._close()
            raise RuntimeError("Claude Code process died")


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def create_client(
    provider: Literal["anthropic", "openai", "minimax"],
    api_key: str | None = None,
    **kwargs: Any,
) -> ModelClient:
    """Factory: create a ModelClient for the given provider."""
    if provider == "anthropic":
        return AnthropicClient(api_key=api_key)
    if provider == "openai":
        return OpenAIClient(api_key=api_key)
    if provider == "minimax":
        return MiniMaxClient(api_key=api_key, **kwargs)
    raise ValueError(f"Unknown provider: {provider!r}")
