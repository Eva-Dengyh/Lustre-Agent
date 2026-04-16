"""Built-in tools for CodeAgent.

Phase 4 includes the essential file + terminal tools so the agent
can actually write and run code without waiting for Phase 6.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from lustre.models.executor import ToolDef

__all__ = ["get_builtin_tools"]


# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------

def _resolve_path(path: str) -> Path:
    """Resolve a user-provided path to an absolute Path object."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _run(cmd: str, timeout: int = 60) -> str:
    """Run a shell command, return stdout+stderr."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd(),
        )
        output = result.stdout + result.stderr
        return output[:3000]  # truncate long output
    except subprocess.TimeoutExpired:
        return f"[超时] 命令超过 {timeout} 秒"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] {exc}"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_read_file(args: dict[str, Any], task_id: str | None) -> str:
    path = args.get("path", "")
    if not path:
        return "[错误] path 参数必填"
    p = _resolve_path(path)
    if not p.exists():
        return f"[错误] 文件不存在: {path}"
    try:
        text = p.read_text(encoding="utf-8")
        if len(text) > 50_000:
            text = text[:50_000] + "\n[... 内容被截断 ...]"
        return text
    except Exception as exc:  # noqa: BLE001
        return f"[错误] 读取失败: {exc}"


def tool_write_file(args: dict[str, Any], task_id: str | None) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    if not path:
        return "[错误] path 参数必填"
    p = _resolve_path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[成功] 写入 {path}，共 {len(content)} 字符"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] 写入失败: {exc}"


def tool_patch(args: dict[str, Any], task_id: str | None) -> str:
    path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not path or not old_string:
        return "[错误] path 和 old_string 参数必填"
    p = _resolve_path(path)
    if not p.exists():
        return f"[错误] 文件不存在: {path}"
    try:
        text = p.read_text(encoding="utf-8")
        if old_string not in text:
            return f"[错误] 未找到 old_string，请确认内容完全匹配（包括空白字符）"
        new_text = text.replace(old_string, new_string, 1)
        p.write_text(new_text, encoding="utf-8")
        return f"[成功] patch {path}"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] patch 失败: {exc}"


def tool_terminal(args: dict[str, Any], task_id: str | None) -> str:
    command = args.get("command", "")
    timeout = int(args.get("timeout", 60))
    if not command:
        return "[错误] command 参数必填"
    return _run(command, timeout=timeout)


def tool_search_files(args: dict[str, Any], task_id: str | None) -> str:
    """Search files by glob pattern or content regex."""
    pattern = args.get("pattern", "")
    target = args.get("target", "content")
    path = args.get("path", ".")
    file_glob = args.get("file_glob", None)
    limit = int(args.get("limit", 50))

    if not pattern:
        return "[错误] pattern 参数必填"

    p = Path(path).expanduser()
    if not p.exists():
        return f"[错误] 路径不存在: {path}"

    results: list[str] = []

    if target == "files":
        for i, match in enumerate(p.rglob(pattern)):
            if match.is_file():
                results.append(str(match))
                if len(results) >= limit:
                    results.append(f"[... 共超过 {limit} 个结果 ...]")
                    break
    else:
        # Grep-like content search
        try:
            import re
            regex = re.compile(pattern)
        except re.error as e:
            return f"[错误] 无效正则: {e}"
        for i, match in enumerate(p.rglob(file_glob or "*")):
            if not match.is_file():
                continue
            try:
                text = match.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{match}:{lineno}: {line.rstrip()}")
                    if len(results) >= limit:
                        results.append(f"[... 共超过 {limit} 个结果 ...]")
                        break

    if not results:
        return "[无匹配]"
    return "\n".join(results)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def get_builtin_tools() -> list[ToolDef]:
    """Return the list of built-in tools available to CodeAgent."""
    return [
        ToolDef(
            name="read_file",
            description="Read the contents of a file. Returns the full text.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
            function=tool_read_file,
        ),
        ToolDef(
            name="write_file",
            description="Write content to a file. Creates parent directories if needed. "
                        "Warning: overwrites the entire file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            function=tool_write_file,
        ),
        ToolDef(
            name="patch",
            description="Replace a specific string in a file. Use for targeted edits. "
                        "old_string must match exactly including whitespace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Exact text to find and replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
            function=tool_patch,
        ),
        ToolDef(
            name="terminal",
            description="Run a shell command. Returns stdout + stderr combined.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)"},
                },
                "required": ["command"],
            },
            function=tool_terminal,
        ),
        ToolDef(
            name="search_files",
            description="Search for files by name (glob) or search inside files (regex).",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern or regex"},
                    "target": {"type": "string", "enum": ["content", "files"], "description": "'content' to grep, 'files' to glob"},
                    "path": {"type": "string", "description": "Directory to search in (default '.')"},
                    "file_glob": {"type": "string", "description": "Filter files by glob (e.g. '*.py')"},
                    "limit": {"type": "integer", "description": "Max results (default 50)"},
                },
                "required": ["pattern", "target"],
            },
            function=tool_search_files,
        ),
    ]
