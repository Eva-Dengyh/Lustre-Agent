"""Built-in tools for CodeAgent — registered via @register_tool.

Phase 6: all tools now register themselves with the central ToolRegistry.
The get_builtin_tools() function returns tools from the registry.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from lustre.tools.registry import ToolDef, get_tool_registry, register_tool

__all__ = ["get_builtin_tools"]


# -----------------------------------------------------------------------------
# Path helper
# -----------------------------------------------------------------------------

def _resolve_path(path: str) -> Path:
    """Resolve a user-provided path to an absolute Path object."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


# -----------------------------------------------------------------------------
# Tool 1: read_file
# -----------------------------------------------------------------------------

def _tool_read_file(args: dict[str, Any], task_id: str | None) -> str:
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


# Register
_read_file_schema = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "要读取的文件路径"},
    },
    "required": ["path"],
}
register_tool(
    name="read_file",
    description="读取文件内容。如果文件很大，只返回前 50000 字符。",
    parameters=_read_file_schema,
    owner="builtin",
)(_tool_read_file)


# -----------------------------------------------------------------------------
# Tool 2: write_file
# -----------------------------------------------------------------------------

def _tool_write_file(args: dict[str, Any], task_id: str | None) -> str:
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


_write_file_schema = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "要写入的文件路径"},
        "content": {"type": "string", "description": "文件内容（会覆盖原文件）"},
    },
    "required": ["path", "content"],
}
register_tool(
    name="write_file",
    description="写入文件。如果文件已存在则覆盖。如果目录不存在则自动创建。",
    parameters=_write_file_schema,
    owner="builtin",
)(_tool_write_file)


# -----------------------------------------------------------------------------
# Tool 3: patch
# -----------------------------------------------------------------------------

def _tool_patch(args: dict[str, Any], task_id: str | None) -> str:
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
            return "[错误] 未找到 old_string，请确认内容完全匹配（包括空白字符）"
        new_text = text.replace(old_string, new_string, 1)
        p.write_text(new_text, encoding="utf-8")
        return f"[成功] patch {path}"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] patch 失败: {exc}"


_patch_schema = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "要修改的文件路径"},
        "old_string": {
            "type": "string",
            "description": "要替换的原始文字（必须精确匹配，包括空白字符）",
        },
        "new_string": {"type": "string", "description": "替换后的新文字"},
    },
    "required": ["path", "old_string", "new_string"],
}
register_tool(
    name="patch",
    description="精确替换文件中的一小段文字。用 old_string 找到目标位置，用 new_string 替换。"
                "适用于修改函数体、错误信息、注释等局部内容。",
    parameters=_patch_schema,
    owner="builtin",
)(_tool_patch)


# -----------------------------------------------------------------------------
# Tool 4: terminal
# -----------------------------------------------------------------------------

def _tool_terminal(args: dict[str, Any], task_id: str | None) -> str:
    command = args.get("command", "")
    timeout = int(args.get("timeout", 60))
    if not command:
        return "[错误] command 参数必填"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd(),
        )
        output = result.stdout + result.stderr
        return output[:3000] or "(命令无输出)"
    except subprocess.TimeoutExpired:
        return f"[超时] 命令超过 {timeout} 秒"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] {exc}"


_terminal_schema = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要执行的 Shell 命令"},
        "timeout": {
            "type": "integer",
            "description": "超时秒数（默认 60，最大 300）",
        },
    },
    "required": ["command"],
}
register_tool(
    name="terminal",
    description="执行一条 Shell 命令。返回 stdout + stderr 的合并内容。"
                "用于运行测试、构建脚本、git 操作等。",
    parameters=_terminal_schema,
    owner="builtin",
)(_tool_terminal)


# -----------------------------------------------------------------------------
# Tool 5: search_files
# -----------------------------------------------------------------------------

def _tool_search_files(args: dict[str, Any], task_id: str | None) -> str:
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
        for match in p.rglob(pattern):
            if match.is_file():
                results.append(str(match))
                if len(results) >= limit:
                    results.append(f"[... 共超过 {limit} 个结果 ...]")
                    break
    else:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"[错误] 无效正则: {e}"
        for match in p.rglob(file_glob or "*"):
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


_search_files_schema = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "正则表达式（content 模式）或 glob 模式（files 模式）"},
        "target": {
            "type": "string",
            "enum": ["content", "files"],
            "description": "'content' 搜索文件内容（正则），'files' 搜索文件名（glob）",
        },
        "path": {"type": "string", "description": "搜索根目录（默认 '.'）"},
        "file_glob": {"type": "string", "description": "限定文件类型，如 '*.py'（仅 content 模式）"},
        "limit": {"type": "integer", "description": "最大结果数（默认 50）"},
    },
    "required": ["pattern", "target"],
}
register_tool(
    name="search_files",
    description="搜索文件：'content' 模式用正则搜索文件内容，'files' 模式用 glob 搜索文件名。",
    parameters=_search_files_schema,
    owner="builtin",
)(_tool_search_files)


# -----------------------------------------------------------------------------
# Public getter
# -----------------------------------------------------------------------------

def get_builtin_tools() -> list[ToolDef]:
    """Return all built-in tools from the registry.

    Note: this assumes tools have already been imported (which happens
    when this module is imported). Import this module to register tools.
    """
    return get_tool_registry().get_tools(owner="builtin")
