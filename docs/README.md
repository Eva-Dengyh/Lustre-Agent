# Lustre-Agent 教程目录

> **如何使用本教程**
> - 按天顺序阅读：Day 1 → Day 7 是一条完整学习路径，每天一篇 md，做完即交付一个可运行的阶段性成果。
> - 每篇 md 采用 **八段式模板**（见 [`templates/day-template.md`](templates/day-template.md)），可直接丢给 AI 实现该阶段代码。
> - 附录（Appendix）可在核心 7 天完成后任意顺序阅读。

---

## 🎯 学习目标

读完本教程后，你将能：

1. 独立设计并实现一个 **多 Agent 系统的架构**（不是"抄一个 demo"，而是知道每个模块为什么这样分）
2. 熟练使用 **LangGraph** 的 State / Node / Edge / Checkpointer / Conditional Edge
3. 理解 **Supervisor 拓扑**、Agent handoff、循环与终止判据
4. 懂得如何把 **Tool / Memory / LLM / 控制流** 解耦
5. 能把自己的项目**文档化到"AI 可执行"的程度**

## 📅 核心 7 天

| Day | 文档 | 概念内核 | 产物验收 |
|---|---|---|---|
| 1 | [Day 1 · 起步 & Hello Agent](day1-hello-agent.md) | Agent loop 四要素；uv 项目结构；第三方中转站接入 | `uv run lustre hello` 打印一句 AI 回复 |
| 2 | [Day 2 · LangGraph 地基](day2-langgraph-basics.md) | `StateGraph` / Node / Edge / `MemorySaver` / `thread_id` | 默认 CLI 进入聊天模式，多轮 + 历史可回放 |
| 3 | [Day 3 · Tool Use](day3-tool-use.md) | Tool Calling、`ToolNode`、MCP-friendly schema、白名单沙箱 | Agent 能 `read_file` / `write_file` / `run_shell` |
| 4 | [Day 4 · Planner Agent](day4-planner.md) | Structured Output、JSON Schema、prompt 工程、命令路由 | `/code <需求>` 打印 Task DAG |
| 5 | [Day 5 · Coder + Supervisor](day5-coder-supervisor.md) | Supervisor 拓扑、subgraph、agent handoff | Planner → Coder 两棒跑通 |
| 6 | [Day 6 · Reviewer + 闭环](day6-reviewer-loop.md) | Conditional Edge、循环 + 最大重试、失败回归 | 三 agent 跑通 FastAPI demo |
| 7 | [Day 7 · 打磨 & 发布](day7-polish-release.md) | Trace / 成本 / CI / README；如何写一篇 Appendix | GitHub Release |

## 📦 扩展包（Appendix）

| 附录 | 主题 | 依赖 |
|---|---|---|
| [A · 长期记忆](appendix-a-memory.md) | 向量库 + `store` 接口，把会话/审查结论沉淀为经验 | Day 6 |
| [B · MCP 接入](appendix-b-mcp.md) | 把外部 MCP server 作为 tool 挂到 Coder | Day 3 |
| [C · Skill 能力包](appendix-c-skill.md) | 把 "prompt + tool + 验收" 打包为可 `/skill load` 的能力包 | Day 4 |
| [D · Docker 化](appendix-d-docker.md) | 容器化、`docker compose`、代码执行沙箱 | Day 7 |

## 🧭 阅读顺序建议

- **最短路径**（1 天速通）：Day 1 → Day 2 → Day 5 → Day 6（跳过 Day 3/4/7，但要抄代码）
- **学习路径**（推荐）：Day 1 → Day 7 顺序阅读 + 每天动手
- **查资料**：直接搜对应 Day 的"概念内核"关键字

## 🔗 相关资源

- LangGraph 官方文档：https://langchain-ai.github.io/langgraph/
- LangChain：https://python.langchain.com/
- MCP（Model Context Protocol）：https://modelcontextprotocol.io/
