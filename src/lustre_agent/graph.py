from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .agents.chat import make_chat_node
from .memory import make_checkpointer


class State(TypedDict):
    messages: Annotated[list, add_messages]


def build_graph(llm=None, checkpointer=None):
    if checkpointer is None:
        checkpointer = make_checkpointer()
    g = StateGraph(State)
    g.add_node("chat", make_chat_node(llm))
    g.add_edge(START, "chat")
    g.add_edge("chat", END)
    return g.compile(checkpointer=checkpointer)
