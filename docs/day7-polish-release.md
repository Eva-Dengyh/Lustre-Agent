---
day: 7
title: "打磨 & 发布"
status: draft
est_minutes: 120
depends_on: [day6]
---

# Day 7 · 打磨 & 发布

## 0. 30 秒速览

- **上一天终点**：三 agent 完整闭环跑通 FastAPI demo
- **今天终点**：项目具备观测、成本统计、基础 CI、像样的 README；推上 GitHub 能被别人 star 并按文档复现
- **新增能力**：把"能跑"变成"能发"的工程化能力

## 1. 你将学到的概念（Why）

- **可观测性**：trace 每一步节点的输入/输出/耗时/token；LangSmith 或本地 `jsonl` 二选一
- **成本控制**：每次 LLM 调用记录 `prompt_tokens / completion_tokens`；会话结束时汇总
- **CI 基线**：GitHub Actions 跑 `ruff`（lint）+ `pytest`（smoke tests）
- **发布清单**：LICENSE、README 徽章、贡献指南、v0.1.0 tag
- **文档写作**：如何为后人写一篇新的 Appendix（复用八段式模板）

## 2. 前置条件

- 已完成 Day 6
- 有 GitHub 账号与空仓库
- 新增依赖：`ruff`、`rich`（若未装）

## 3. 目标产物

```tree
.github/workflows/
├── ci.yml                  ← 新增
src/lustre_agent/
├── trace.py                ← 新增：本地 jsonl tracer（可切 LangSmith）
├── cost.py                 ← 新增：token 统计与汇总
├── cli.py                  ← 修改：`/stats`、`--trace` 选项
docs/
├── CONTRIBUTING.md         ← 新增
├── ARCHITECTURE.md         ← 新增：整体架构图 + state 演化时序图
├── day7-polish-release.md  ← 本文
README.md                   ← 完善（徽章、Quickstart 截图 gif 位置）
```

## 4. 实现步骤

### Step 1 — 本地 trace

- 在每个 node 入口/出口发事件到 `.lustre/traces/<thread_id>.jsonl`
- 用 LangGraph 的 `config` + `callbacks` 钩子，不侵入业务代码
- `--trace` CLI flag 控制是否开；默认关

### Step 2 — 成本统计

- 订阅 `on_llm_end` 回调；累加到一个 `CostTracker` 实例
- `/stats` 命令在 REPL 中打印本 session 的消耗

### Step 3 — CI

- `ci.yml`：trigger on push/PR；job 装 uv → `uv sync` → `uv run ruff check` → `uv run pytest tests/ -m smoke`
- 所有 smoke test 打 `@pytest.mark.smoke` 标签

### Step 4 — 文档完善

- `ARCHITECTURE.md`：一张总图 + State 演化时序图 + 每个 agent 的职责表
- `CONTRIBUTING.md`：开发环境、如何加新 agent / tool / appendix
- `README.md` 加徽章、Quickstart gif 占位

### Step 5 — 如何写 Appendix

八段式模板同样适用于 Appendix。新附录需声明：

- `depends_on`（哪些 Day 是前置）
- 侵入点：改哪些 State 字段、哪些节点
- 兼容性：是否打破核心 7 天的接口（答案应为"不打破"）

### Step 6 — 发布

- `git init && git add . && git commit -m "v0.1.0 initial release"`
- 创建 GitHub 仓库 → `git push`
- `git tag v0.1.0 && git push --tags`
- 在 Release 页粘贴 README 的 Quickstart

## 5. 关键代码骨架

```python
# src/lustre_agent/trace.py
from langchain_core.callbacks import BaseCallbackHandler

class JsonlTracer(BaseCallbackHandler):
    def __init__(self, path): ...
    def on_chain_start(self, *a, **kw): ...
    def on_llm_end(self, *a, **kw): ...
```

```python
# src/lustre_agent/cost.py
from dataclasses import dataclass

@dataclass
class CostTracker:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # 可选：美元估算表
    def absorb(self, llm_output): ...
    def summary(self) -> dict: ...
```

```yaml
# .github/workflows/ci.yml（示意）
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check
      - run: uv run pytest -m smoke
```

## 6. 验收

### 6.1 手动

- `uv run lustre --trace` 运行一次，`.lustre/traces/*.jsonl` 有记录
- REPL 输入 `/stats` 看到 token 汇总
- `git push` 后 GitHub Actions 第一次跑 **绿**

### 6.2 自动

```bash
uv run pytest tests/day7_smoke.py -v
```

检查项：

- [ ] `JsonlTracer` 能被 LangGraph 接收且不报错
- [ ] `CostTracker.summary()` 返回有 prompt/completion 两字段
- [ ] `uv run ruff check src/` 为 0 errors

## 7. 常见坑

- LangSmith API key 没配不应让程序崩溃：trace 失败要静默降级到 stdout
- token 统计：不同模型返回 usage 字段的方式不一样，做好兜底
- CI 第一次很容易挂在 `uv sync` 的锁文件/索引；建议先本地 `uv lock` 再 push

## 8. 小结 & 下一步

- **今日核心**：把作品变成作品集——观测、测试、发布、文档
- **你现在可以**：在 GitHub 上公开 Lustre-Agent v0.1.0
- **下一步（Appendix）**：
  - [A · 长期记忆](appendix-a-memory.md)：把经验沉淀下来
  - [B · MCP 接入](appendix-b-mcp.md)：借外部生态
  - [C · Skill 能力包](appendix-c-skill.md)：封装可复用能力
  - [D · Docker 化](appendix-d-docker.md)：容器化与沙箱
