---
day: 2
title: "LangGraph 地基 —— State / Node / Edge / Memory"
status: draft
est_minutes: 120
depends_on: [day1]
---

# Day 2 · LangGraph 地基

## 0. 30 秒速览

- **上一天终点**：`lustre hello` 跑通单次 LLM 调用
- **今天终点**：`lustre`（无参数）进入聊天模式；多轮对话自动记得上文；`lustre history` / `lustre replay <id>` 可查/可回放
- **新增能力**：LangGraph 核心 API 上手；短期记忆与会话持久化

## 1. 概念（Why）

- **`StateGraph`**：图状工作流的建模单位。节点是函数，边是流转规则，`State` 在节点间流动
- **State**：全图共享的数据结构（TypedDict / pydantic）。Message 列表用 `add_messages` reducer 做追加合并
- **Checkpointer（`MemorySaver`/`SqliteSaver`）**：每次节点跑完自动保存 State 快照
- **`thread_id`**：会话隔离键；同一个 `thread_id` 的多次调用会从 checkpoint 继续

```mermaid
flowchart LR
    subgraph Graph
      direction LR
      S([START]) --> chat[chat_node]
      chat --> E([END])
    end
    chat <-- State + checkpoint --> store[(SQLite)]
```

## 2. 前置条件

- 已完成 Day 1
- 新增依赖：`langgraph`、`langchain-core`、`rich`（CLI 美化）、`prompt_toolkit`（输入行）
- 知识假设：了解 Python TypedDict、基础装饰器

## 3. 目标产物

```tree
src/lustre_agent/
├── graph.py              ← 新增：图组装
├── memory.py             ← 新增：checkpointer 工厂 + thread 管理
├── agents/
│   ├── __init__.py       ← 新增
│   └── chat.py           ← 新增：默认聊天 agent 节点
├── cli.py                ← 修改：默认进入 chat REPL；新增 history/replay
tests/
├── day2_smoke.py         ← 新增
```

CLI 行为约定：

| 输入 | 行为 |
|---|---|
| `uv run lustre`（无子命令） | 进入聊天 REPL（默认 agent） |
| REPL 内 `/history` | 列出历史 thread_id + 首句 |
| REPL 内 `/replay <id>` | 打印指定 thread 的完整消息 |
| REPL 内 `/new` | 开新会话 |
| REPL 内 `/exit` | 退出 |

> **注意**：`/code` 入口是 Day 4 的事，本日先不实现。

## 4. 实现步骤

### Step 1 — 定义 State

- `State = TypedDict("State", {"messages": Annotated[list, add_messages]})`
- 之后章节会追加字段（plan / tasks / review_result 等），本章只有 messages

### Step 2 — `memory.py`：checkpointer 工厂

- 默认 `SqliteSaver`，文件位于 `LUSTRE_DATA_DIR`（默认 `.lustre/checkpoints.sqlite`）
- 暴露 `list_threads()` / `get_thread_messages(thread_id)` 辅助函数

### Step 3 — `agents/chat.py`：聊天节点

- 输入 State → 调 `get_llm()` → 把 AIMessage append 回 State
- 使用 system prompt 声明身份："你是 Lustre-Agent 的默认聊天助手"

### Step 4 — `graph.py`：组装图

```python
g = StateGraph(State)
g.add_node("chat", chat_node)
g.add_edge(START, "chat")
g.add_edge("chat", END)
return g.compile(checkpointer=make_checkpointer())
```

### Step 5 — `cli.py` REPL 逻辑

- 默认命令改成启动 REPL 而非 `hello`
- REPL 每轮读一行输入，检测 `/` 前缀走特殊命令，否则 `graph.invoke({"messages": [HumanMessage(...)]}, config={"configurable": {"thread_id": ...}})`

### Step 6 — smoke test

- 构图能编译
- 同一 thread_id 两次调用后，State.messages 长度为 4（user+ai+user+ai）
- 不同 thread_id 互不串扰

## 5. 关键代码骨架

```python
# src/lustre_agent/graph.py
from langgraph.graph import StateGraph, START, END
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]

def build_graph():
    ...
```

```python
# src/lustre_agent/memory.py
from langgraph.checkpoint.sqlite import SqliteSaver

def make_checkpointer(): ...
def list_threads() -> list[dict]: ...
def get_thread_messages(thread_id: str) -> list: ...
```

## 6. 验收

### 6.1 手动

```bash
uv run lustre
# 进入 REPL，输入 "我叫 Eva"
# 再输入 "我叫什么？"，预期模型答出 Eva
# /history 看到当前会话 id
# /exit
# uv run lustre replay <上面的 id>  → 打印完整对话
```

### 6.2 自动

```bash
uv run pytest tests/day2_smoke.py -v
```

检查项：

- [ ] `build_graph()` 能 compile
- [ ] 同 thread 两轮对话后 messages 长度 == 4
- [ ] 不同 thread 状态隔离

## 7. 常见坑

- SQLite checkpointer 多线程访问需 `check_same_thread=False`
- `add_messages` reducer 会去重同 id 消息，手工构造消息时不要忘记 id

## 8. 小结 & 下一步

- **今日核心**：用最小图 + checkpointer 完成"能记事"的聊天 agent
- **你现在可以**：作为 ChatGPT-lite 本地用
- **明日（Day 3）预告**：加 tool，让 agent 开始"动手"
