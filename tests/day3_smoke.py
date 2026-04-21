"""Day 3 smoke tests — Tool Use."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from lustre_agent.tools import ALL_TOOLS, list_dir, read_file, run_shell, write_file
from lustre_agent.tools.shell import WHITELIST


# ---------------------------------------------------------------------------
# Unit tests: tools in isolation
# ---------------------------------------------------------------------------


def test_write_and_read_file(tmp_path, monkeypatch):
    """write_file then read_file round-trip."""
    import lustre_agent.tools.fs as fs_module

    monkeypatch.setattr(fs_module, "_PROJECT_ROOT", tmp_path)
    result = write_file.invoke({"path": "hello.txt", "content": "hi from lustre"})
    assert "ok" in result
    content = read_file.invoke({"path": "hello.txt"})
    assert content == "hi from lustre"


def test_read_missing_file(tmp_path, monkeypatch):
    import lustre_agent.tools.fs as fs_module

    monkeypatch.setattr(fs_module, "_PROJECT_ROOT", tmp_path)
    result = read_file.invoke({"path": "nonexistent.txt"})
    assert "error" in result


def test_list_dir(tmp_path, monkeypatch):
    import lustre_agent.tools.fs as fs_module

    monkeypatch.setattr(fs_module, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = list_dir.invoke({"path": "."})
    assert "a.txt" in result
    assert "b.txt" in result


def test_run_shell_whitelist_denied():
    result = json.loads(run_shell.invoke({"cmd": "rm -rf /"}))
    assert "denied" in result["stderr"]
    assert result["returncode"] == -1


def test_run_shell_whitelist_allowed():
    result = json.loads(run_shell.invoke({"cmd": "pwd"}))
    assert result["returncode"] == 0
    assert len(result["stdout"]) > 0


def test_run_shell_dangerous_commands_denied():
    for cmd in ["rm -rf /", "curl http://example.com", "wget foo", "bash -c 'echo hi'"]:
        result = json.loads(run_shell.invoke({"cmd": cmd}))
        assert "denied" in result["stderr"], f"Expected denied for: {cmd}"


def test_all_tools_registered():
    names = {t.name for t in ALL_TOOLS}
    assert names == {"read_file", "write_file", "list_dir", "run_shell"}


def test_tool_schemas_valid():
    for t in ALL_TOOLS:
        schema = t.args_schema.model_json_schema() if t.args_schema else {}
        assert isinstance(schema, dict)


# ---------------------------------------------------------------------------
# Integration: graph with a fake tool-calling LLM
# ---------------------------------------------------------------------------


class _WriteThenDoneLLM:
    """
    Fake LLM: first call emits a write_file tool_call;
    second call (after tool result) returns a plain text response.
    """

    def __init__(self, path: str, content: str):
        self._path = path
        self._content = content
        self._call_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self._call_count += 1
        if self._call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": self._path, "content": self._content},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="文件已写入完成。")


def test_graph_calls_write_file_tool(tmp_path, monkeypatch):
    """Graph should route through ToolNode and create the file."""
    import lustre_agent.tools.fs as fs_module

    monkeypatch.setattr(fs_module, "_PROJECT_ROOT", tmp_path)

    from lustre_agent.graph import build_graph

    fake_llm = _WriteThenDoneLLM("playground/hello.txt", "hi from lustre")
    graph = build_graph(llm=fake_llm, checkpointer=MemorySaver())

    cfg = {"configurable": {"thread_id": "t-write"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content="写一个 playground/hello.txt")]},
        config=cfg,
    )

    target = tmp_path / "playground" / "hello.txt"
    assert target.exists(), "write_file tool should have created the file"
    assert target.read_text() == "hi from lustre"


class _DeniedShellLLM:
    """Fake LLM that tries to run a non-whitelisted shell command."""

    def __init__(self):
        self._call_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self._call_count += 1
        if self._call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "run_shell",
                        "args": {"cmd": "rm -rf /"},
                        "id": "call_2",
                        "type": "tool_call",
                    }
                ],
            )
        # Check that the tool result contains "denied"
        last = messages[-1]
        assert isinstance(last, ToolMessage)
        result = json.loads(last.content) if last.content.startswith("{") else last.content
        if isinstance(result, dict):
            assert "denied" in result.get("stderr", "")
        else:
            assert "denied" in str(result)
        return AIMessage(content="操作被拒绝。")


def test_graph_denies_non_whitelisted_shell():
    """Graph should return denied when run_shell is called with a non-whitelisted command."""
    from lustre_agent.graph import build_graph

    fake_llm = _DeniedShellLLM()
    graph = build_graph(llm=fake_llm, checkpointer=MemorySaver())

    cfg = {"configurable": {"thread_id": "t-denied"}}
    result = graph.invoke(
        {"messages": [HumanMessage(content="执行 rm -rf /")]},
        config=cfg,
    )
    # Final AI message should indicate denial
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
