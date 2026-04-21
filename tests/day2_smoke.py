import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver


class _EchoLLM:
    """Fake LLM for tests — no API calls."""

    def invoke(self, messages):
        return AIMessage(content="echo")


@pytest.fixture
def graph():
    from lustre_agent.graph import build_graph
    return build_graph(llm=_EchoLLM(), checkpointer=MemorySaver())


def test_graph_compiles(graph):
    assert graph is not None


def test_same_thread_accumulates_messages(graph):
    cfg = {"configurable": {"thread_id": "t-same"}}
    graph.invoke({"messages": [HumanMessage(content="first")]}, config=cfg)
    result = graph.invoke({"messages": [HumanMessage(content="second")]}, config=cfg)
    assert len(result["messages"]) == 4  # human, ai, human, ai


def test_different_threads_are_isolated(graph):
    cfg_a = {"configurable": {"thread_id": "t-a"}}
    cfg_b = {"configurable": {"thread_id": "t-b"}}
    graph.invoke({"messages": [HumanMessage(content="hello")]}, config=cfg_a)
    result_b = graph.invoke({"messages": [HumanMessage(content="world")]}, config=cfg_b)
    # thread-b should only have its own 2 messages
    assert len(result_b["messages"]) == 2
