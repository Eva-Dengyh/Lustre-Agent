from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .agents.chat import make_chat_node
from .memory import make_checkpointer
from .tools import ALL_TOOLS


class State(TypedDict):
    messages: Annotated[list, add_messages]


def build_graph(llm=None, checkpointer=None):
    if checkpointer is None:
        checkpointer = make_checkpointer()
    g = StateGraph(State)
    g.add_node("chat", make_chat_node(llm))
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.add_edge(START, "chat")
    g.add_conditional_edges("chat", tools_condition, {"tools": "tools", END: END})
    g.add_edge("tools", "chat")
    return g.compile(checkpointer=checkpointer)
