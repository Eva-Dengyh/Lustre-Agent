import json
import shlex
import subprocess
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, Field

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

WHITELIST = {"python", "pytest", "uv", "ls", "cat", "pwd", "grep", "find"}


class RunShellArgs(BaseModel):
    cmd: str = Field(..., description="要执行的 shell 命令")


@tool("run_shell", args_schema=RunShellArgs)
def run_shell(cmd: str) -> str:
    """在项目根目录执行白名单命令，返回 JSON 字符串 {returncode, stdout, stderr}。"""
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return json.dumps({"returncode": -1, "stdout": "", "stderr": f"parse error: {e}"})

    if not parts:
        return json.dumps({"returncode": -1, "stdout": "", "stderr": "error: empty command"})

    executable = parts[0]
    if executable not in WHITELIST:
        return json.dumps({
            "returncode": -1,
            "stdout": "",
            "stderr": f"denied: '{executable}' is not in the allowed command whitelist",
        })

    try:
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_PROJECT_ROOT),
        )
        return json.dumps({
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"returncode": -1, "stdout": "", "stderr": "error: command timed out after 30s"})
    except Exception as e:
        return json.dumps({"returncode": -1, "stdout": "", "stderr": f"error: {e}"})
