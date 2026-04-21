import os
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path: str) -> Path:
    """Resolve path relative to project root; reject traversals outside it."""
    resolved = (_PROJECT_ROOT / path).resolve()
    if not str(resolved).startswith(str(_PROJECT_ROOT)):
        raise ValueError(f"Path {path!r} escapes project root")
    return resolved


class ReadFileArgs(BaseModel):
    path: str = Field(..., description="相对项目根的路径")


@tool("read_file", args_schema=ReadFileArgs)
def read_file(path: str) -> str:
    """读取文件内容并返回字符串。"""
    target = _resolve(path)
    if not target.exists():
        return f"error: file not found: {path}"
    if not target.is_file():
        return f"error: not a file: {path}"
    return target.read_text(encoding="utf-8")


class WriteFileArgs(BaseModel):
    path: str = Field(..., description="相对项目根的路径")
    content: str = Field(..., description="写入的内容")


@tool("write_file", args_schema=WriteFileArgs)
def write_file(path: str, content: str) -> str:
    """将内容写入文件（自动创建父目录）。"""
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"ok: wrote {len(content)} chars to {path}"


class ListDirArgs(BaseModel):
    path: str = Field(".", description="相对项目根的目录路径，默认为项目根")


@tool("list_dir", args_schema=ListDirArgs)
def list_dir(path: str = ".") -> str:
    """列出目录内容，返回换行分隔的条目列表。"""
    target = _resolve(path)
    if not target.exists():
        return f"error: directory not found: {path}"
    if not target.is_dir():
        return f"error: not a directory: {path}"
    entries = sorted(os.listdir(target))
    return "\n".join(entries) if entries else "(empty)"
