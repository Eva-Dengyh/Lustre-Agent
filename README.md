# Lustre-Agent

> 一个从零开始、面向学习的 **多 Agent 通用助理** 项目；也是一份 **AI 可执行的开源教程**——每一篇 md 丢给 AI，AI 能按文档把这段功能实现出来。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-latest-green.svg)](https://github.com/langchain-ai/langgraph)

---

## ✨ 这个项目是什么

- **一个 CLI 通用助理**：默认是聊天模式，输入 `/code <需求>` 切入多 Agent 协作
- **内置三个 Agent**：
  - **Planner**：把需求拆成任务 DAG
  - **Coder**：按任务写代码
  - **Reviewer**：审核 + 跑测试，不过则打回 Coder（带最大重试）
- **Demo 目标**：给它一句"做一个带测试的 FastAPI todo API"，它能交付一个可跑通 `pytest` 的小项目

## 🎯 教程属性

- **七天可复现**：按天一篇 md，七天搭完
- **AI 可执行**：每篇 md 采用八段式模板，含目标产物、实现步骤、验收标准；AI 按此可自动实现
- **架构优先**：重点不是代码量而是理解 LangGraph + Supervisor 拓扑 + state/tool/memory 分层
- **可扩展**：核心 7 天 + 4 个扩展包（长期记忆 / MCP / Skill / Docker）

## 🚀 快速开始

```bash
# 1. 克隆
git clone https://github.com/<your-user>/Lustre-Agent.git
cd Lustre-Agent

# 2. 用 uv 安装
uv sync

# 3. 配置第三方中转站
cp .env.example .env
# 编辑 .env，填入你的 OPENAI_API_BASE 和 OPENAI_API_KEY

# 4. 启动 CLI
uv run lustre
```

CLI 命令：

| 命令 | 作用 |
|---|---|
| *(默认)* | 进入普通对话模式（单 agent） |
| `/code <需求>` | 切到多 Agent 协作模式 |
| `/history` | 列出历史会话 |
| `/replay <id>` | 回放历史会话 |
| `/help` | 查看命令 |
| `/exit` | 退出 |

## 📚 教程目录

完整阅读顺序见 [`docs/README.md`](docs/README.md)。速览：

| Day | 主题 | 关键交付 |
|---|---|---|
| [Day 1](docs/day1-hello-agent.md) | 起步 & Hello Agent | 项目脚手架 + 最小单 agent |
| [Day 2](docs/day2-langgraph-basics.md) | LangGraph 地基 | 默认聊天模式 + 多轮记忆 + 历史回放 |
| [Day 3](docs/day3-tool-use.md) | Tool Use | Agent 会读写文件、执行 shell |
| [Day 4](docs/day4-planner.md) | Planner Agent | `/code` 入口 + 任务 DAG |
| [Day 5](docs/day5-coder-supervisor.md) | Coder + Supervisor 拓扑 | Planner → Coder 两棒跑通 |
| [Day 6](docs/day6-reviewer-loop.md) | Reviewer + 闭环 | 三 Agent 全链路跑通 FastAPI demo |
| [Day 7](docs/day7-polish-release.md) | 打磨 & 发布 | 观测 + README + GitHub Release |

扩展包：

- [Appendix A · 长期记忆](docs/appendix-a-memory.md)
- [Appendix B · MCP 接入](docs/appendix-b-mcp.md)
- [Appendix C · Skill 能力包](docs/appendix-c-skill.md)
- [Appendix D · Docker 化](docs/appendix-d-docker.md)

## 🏗 架构预览

```
           ┌──────────────┐
 user ───▶ │   Supervisor │ ◀────────────────────┐
           └──────┬───────┘                      │
                  │ route                        │
      ┌───────────┼────────────┐                 │
      ▼           ▼            ▼                 │
 ┌────────┐  ┌────────┐  ┌──────────┐            │
 │Planner │  │ Coder  │  │ Reviewer │ ─ fail ────┘
 └────────┘  └────────┘  └────┬─────┘
                              │ pass
                              ▼
                         final answer
```

- **State**：通过 `langgraph.StateGraph` 在节点间流转；`MemorySaver` 做 checkpoint，`thread_id` 支持回放
- **Tools**：以 MCP-friendly schema 定义，见 `src/lustre_agent/tools/`
- **LLM**：统一走第三方 OpenAI 兼容中转站

## 🤝 贡献 & 反馈

本项目定位是**教学仓库**，欢迎以 Issue 形式提教程改进建议，或以 PR 形式加 Appendix。

## 📄 License

[MIT](LICENSE)
