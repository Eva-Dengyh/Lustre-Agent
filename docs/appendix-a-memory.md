---
appendix: A
title: "长期记忆（Long-term Memory）"
status: draft
est_minutes: 90
depends_on: [day6]
---

# Appendix A · 长期记忆

> 把"会话过后就丢"的短期记忆（checkpointer）升级为"跨会话可检索的经验库"。

## 0. 30 秒速览

- **为什么**：Reviewer 发现过的坑、Coder 常用的套路、用户的偏好，跨会话就丢了太可惜
- **做什么**：引入向量库 + `BaseStore` 接口，把关键片段写入；每次 Planner/Coder/Reviewer 开场时先检索 top-K 记忆注入 prompt
- **不做什么**：不是完整的 RAG，也不是"把所有历史都往里塞"；严格控制"什么值得记"

## 1. 概念

- **LangGraph Store**：`BaseStore` 抽象，支持 `put / get / search`；有内置 `InMemoryStore`，生产推荐持久化
- **Namespace**：按 (user_id, topic) 做分区；本项目里 topic = `"review_lessons" | "user_prefs" | "code_snippets"`
- **Embedding**：用中转站的 embedding 端点或 `bge-small` 本地模型
- **写入策略**：
  - Reviewer 每次 pass 后抽取 1–3 条"经验"写入 `review_lessons`
  - 用户在 REPL 主动 `/remember <text>` 写 `user_prefs`
  - Coder 一次任务完成后可选择写入"代码片段"

## 2. 前置条件

- 已完成 Day 6
- 新增依赖：`langgraph-checkpoint-sqlite`、`langchain-openai`（embeddings）、`chromadb` 或 `faiss-cpu`

## 3. 目标产物

```tree
src/lustre_agent/
├── long_term_memory.py      ← 新增：Store 工厂 + 辅助函数
├── agents/
│   ├── reviewer.py          ← 修改：pass 时抽取经验写入
│   ├── planner.py           ← 修改：开场检索 top-K 注入
│   └── coder.py             ← 修改：开场检索 top-K 注入
├── cli.py                   ← 修改：/remember、/memories 命令
tests/
└── appendix_a_smoke.py      ← 新增
```

## 4. 实现步骤

### Step 1 — Store 工厂

- 选型：默认 `InMemoryStore` + 落盘 jsonl（简单）；或接 Chroma
- 暴露 `get_store()` 单例

### Step 2 — 写入 API

```python
def remember(namespace: tuple[str, ...], content: str, meta: dict | None = None): ...
def recall(namespace, query: str, k: int = 5) -> list[dict]: ...
```

### Step 3 — Reviewer 钩子

- Reviewer 的 prompt 加一句："pass 的情况下，请再输出 1–3 条可复用经验（短句）"
- 结构化输出扩展为 `ReviewResult + lessons: list[str]`
- node 结尾调用 `remember(("review_lessons",), lesson)`

### Step 4 — Planner / Coder 检索

- 进入节点时 `ctx = recall(...)`，把 top-K 拼入 system prompt 的"参考经验"段
- 限制最大 token 预算（避免 prompt 爆炸）

### Step 5 — CLI 命令

- `/remember <text>`：手动写 `user_prefs`
- `/memories`：列出当前 namespace 的记忆（分页）
- `/forget <id>`：删除

## 5. 关键代码骨架

```python
# src/lustre_agent/long_term_memory.py
from langgraph.store.memory import InMemoryStore

_store = None
def get_store():
    global _store
    if _store is None: _store = InMemoryStore(index={"embed": ..., "dims": 1536})
    return _store

def remember(namespace, content, meta=None): ...
def recall(namespace, query, k=5): ...
```

## 6. 验收

```bash
uv run lustre
> /remember 我喜欢用 pytest 而不是 unittest
> /code 写一个 add 函数并测试
# 预期：Planner/Coder 生成的测试是 pytest 风格
> /memories
# 预期：能看到刚才写的偏好
```

自动：

```bash
uv run pytest tests/appendix_a_smoke.py -v
```

## 7. 常见坑

- 经验被不加节制地写入会污染 prompt 效果 → 设容量上限 + TTL
- 检索返回低质量结果不如不给：设置相似度下限
- 隐私：记忆落盘默认不开加密，若敏感请自行加钥
