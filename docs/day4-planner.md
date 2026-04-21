---
day: 4
title: "Planner Agent —— 需求 → 任务 DAG"
status: draft
est_minutes: 120
depends_on: [day3]
---

# Day 4 · Planner Agent

## 0. 30 秒速览

- **上一天终点**：单个会动手的 agent
- **今天终点**：REPL 里输入 `/code <需求>` 会切到 Planner，输出一份结构化 `TaskPlan`（任务 DAG）并展示
- **新增能力**：结构化输出、命令分发、为多 agent 编排铺路

## 1. 概念（Why）

- **Structured Output**：用 `with_structured_output(pydantic_model)` 强制 LLM 返回符合 schema 的 JSON；比 "请以 JSON 输出" 稳得多
- **任务 DAG**：每个任务含 `id / description / deps / expected_deliverable`，是后续 Coder / Reviewer 的共同协议
- **命令路由**：在 chat 节点前加一个 router，根据输入首字符 `/` 决定走聊天图还是"多 agent 子图"
- **Prompt 工程**：Planner 的 system prompt 决定了计划质量——单独一节讲

## 2. 前置条件

- 已完成 Day 3
- 依赖已有（本章不需要新装包）
- 知识假设：JSON Schema、pydantic v2、图的拓扑序

## 3. 目标产物

```tree
src/lustre_agent/
├── schemas.py                ← 新增：Task / TaskPlan / ReviewResult
├── agents/
│   └── planner.py            ← 新增：planner_node
├── prompts/
│   ├── __init__.py           ← 新增
│   └── planner.md            ← 新增：planner system prompt
├── graph.py                  ← 修改：加 router + planner 节点；`/code` 分支
├── cli.py                    ← 修改：识别 `/code` 前缀
tests/
├── day4_smoke.py             ← 新增
```

## 4. 实现步骤

### Step 1 — 定义 schemas

- `Task(id, description, deps: list[str], expected_deliverable: str, acceptance: str | None)`
- `TaskPlan(goal: str, tasks: list[Task])`
- `ReviewResult`（预留给 Day 6）

### Step 2 — Planner Prompt

- 放在 `prompts/planner.md`，用 Python `importlib.resources` 读取
- 要点：
  - "你只输出 TaskPlan，不写代码"
  - "尽量少任务、每个任务独立可验收"
  - "DAG 必须无环，deps 引用只能是已定义的任务 id"

### Step 3 — planner_node

- 入：State（含 user 需求）
- 出：`{"plan": TaskPlan}` 字段写回 State
- 用 `get_llm(settings.planner_model).with_structured_output(TaskPlan)`

### Step 4 — State 扩展

- 新增字段：`mode: Literal["chat","code"]`、`plan: TaskPlan | None`
- `mode` 由 router 写入；`plan` 由 planner 写入

### Step 5 — Router + 子图

- 在 START 后加 `router_node`：
  - 最近一条 HumanMessage 以 `/code ` 开头 → `mode="code"`，走 planner
  - 否则 `mode="chat"`，走 Day 2 的 chat 节点
- `g.add_conditional_edges("router", route_by_mode, {"chat": "chat", "plan": "planner"})`
- 目前 planner → END（Day 5 会改成 planner → supervisor）

### Step 6 — CLI 显示计划

- Planner 跑完后在 REPL 里**树形打印** TaskPlan（rich.tree）
- 问用户 "是否继续执行？[Y/n]"（Day 5 才真的执行，今天只打印 + 保存）

### Step 7 — smoke test

- 对 `"/code 写一个加法函数并测试"` 跑 planner，断言返回 TaskPlan、至少 2 个任务、deps 合法

## 5. 关键代码骨架

```python
# src/lustre_agent/schemas.py
from pydantic import BaseModel, Field

class Task(BaseModel):
    id: str
    description: str
    deps: list[str] = Field(default_factory=list)
    expected_deliverable: str
    acceptance: str | None = None

class TaskPlan(BaseModel):
    goal: str
    tasks: list[Task]
```

```python
# src/lustre_agent/agents/planner.py
from ..llm import get_llm
from ..schemas import TaskPlan

def planner_node(state):
    llm = get_llm().with_structured_output(TaskPlan)
    ...
```

## 6. 验收

### 6.1 手动

```bash
uv run lustre
> /code 做一个 FastAPI todo 接口带 pytest
# 预期：打印一棵任务树，例如
#   Goal: 实现 FastAPI todo 接口
#   ├── T1 初始化项目结构
#   ├── T2 实现 models/schemas
#   ├── T3 实现 /todos 路由（deps: T2）
#   └── T4 编写 pytest (deps: T3)
```

### 6.2 自动

```bash
uv run pytest tests/day4_smoke.py -v
```

检查项：

- [ ] 对样例需求，返回 TaskPlan 的 tasks 数 ≥ 2
- [ ] 所有 deps 引用 id 都在 tasks 列表内
- [ ] DAG 无环（拓扑排序成功）
- [ ] `/code` 前缀走 planner，无 `/code` 走 chat

## 7. 常见坑

- `with_structured_output` 在有的模型上需要 `method="function_calling"` 或 `method="json_schema"`
- 任务粒度：太细 → Coder 来回握手太多；太粗 → 不好 review。prompt 里给示例约束粒度
- prompt 里要禁止 Planner 自己写代码——否则它会把代码塞进 description 里

## 8. 小结 & 下一步

- **今日核心**：Planner + 结构化输出 + 命令路由，进入多 agent 世界的门
- **你现在可以**：让 AI 帮你拆任何需求为任务 DAG（即使不执行也有用）
- **明日（Day 5）预告**：Coder 加入 + Supervisor 拓扑，Planner → Coder 开始真的写代码
