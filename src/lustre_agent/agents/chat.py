from langchain_core.messages import SystemMessage

from ..llm import get_llm

SYSTEM_PROMPT = "你是 Lustre-Agent 的默认聊天助手。请用中文或用户所用语言回复。"


def make_chat_node(llm=None):
    def chat_node(state) -> dict:
        _llm = llm or get_llm()
        system = SystemMessage(content=SYSTEM_PROMPT)
        response = _llm.invoke([system] + list(state["messages"]))
        return {"messages": [response]}

    return chat_node
