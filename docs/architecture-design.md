# Lustre Agent — 架构设计文档

> 版本: 0.9.0
> 作者: Eva
> 状态: 已完成 Phase 0-9
> 更新日期: 2026-04-16

---

## 0. 开发前必读：Agent 核心概念

> 每次开始实现新功能前，请先阅读本节。它解释了我们为什么这样设计，以及每个设计决策背后的逻辑。

### 0.1 核心公式

```
Agent = Model + Harness
```

**如果你不是模型，那你就是在做 Harness 工程。**

这句话来自 LangChain 的博客《The Anatomy of an Agent Harness》，是理解整个项目的第一性原理。

- **Model（模型）**：纯粹的推理引擎。给它文字，它输出文字。它不知道文件在哪，不会执行代码，不能持久化状态，不能搜索最新信息。
- **Harness（笼/马具）**：模型之外的所有代码、配置、执行逻辑。把模型变成可用系统的所有工程部分。

Raw model ≠ Agent。Harness 给了它：状态、工具执行、反馈循环、可执行的约束。

### 0.2 模型做不到的事（需要 Harness 来补）

| 模型"做不到"的事 | Harness 如何解决 |
|-----------------|-----------------|
| 不能持久化状态 | 会话存储（SQLite SessionStore） |
| 不能执行代码 | 工具系统（terminal / code execution） |
| 不能获取实时信息 | 工具（web_search） |
| 不能操作文件系统 | 工具（read_file / write_file / patch） |
| 不能并行处理多任务 | 消息总线 + 多 Agent 架构 |
| 不能自己验证结果 | 测试 Agent（Test Agent 运行测试） |
| 不能在长任务中保持方向 | Supervisor 协调 + 人工确认门 |

### 0.3 Lustre Agent 的 Harness 映射

| Harness 组件 | 对应项目模块 | Phase |
|--------------|------------|-------|
| **System Prompts** | `prompts/*.md` | Phase 4 |
| **Tools（工具描述）** | `lustre/tools/` + `prompts/*.md` | Phase 4, 6 |
| **Bundled Infrastructure** | `lustre/bus/`（消息总线） | Phase 1, 9 |
| **Orchestration Logic** | `lustre/supervisor/`（状态机、任务分配） | Phase 3 |
| **Durable Storage** | `lustre/session/`（SQLite） | Phase 7 |
| **Skill System** | `lustre/skills/`（可加载 prompt 模板） | Phase 5 |
| **CLI** | `lustre/cli.py` + `lustre_cli/` | Phase 0, 8 |

### 0.4 设计的核心原则

#### 原则 1：人机协同优先

模型会出错、会跑偏方向。我们把"人工确认"做成框架级约束，而不是可选项。

- Supervisor 在每个 Agent 执行前暂停，等用户说 `/go`
- 调研结果出来后问用户 `/accept`
- 代码完成后（可选）问用户是否满意再测试

这不是功能，是**设计哲学**。掌控感始终在用户手里。

#### 原则 2：Harness 要尽量薄

Harness 是手段，不是目的。Harness 的职责是**让模型做有用的事**，而不是替代模型思考。

体现：
- Supervisor 只做协调（理解任务 → 拆解 → 分配 → 聚合），不写代码
- 专业 Agent 拿到任务后自主决定怎么做
- 工具系统给模型提供能力，不强制模型用特定方式工作

#### 原则 3：确定性逻辑在 Harness，推理在 Model

模型擅长推理，但不可靠。确定性逻辑（流程控制、状态机、错误处理）必须在 Harness 层处理。

反例：让模型自己决定是否需要重试。→ 模型会过度思考。
正确做法：Harness 定义重试策略（超过 N 次失败 → 询问用户）。

#### 原则 4：先让单 Agent 跑通，再扩展多 Agent

Phase 4 先让 Code Agent 单独跑通（接收任务 → 调用 LLM → 使用工具 → 返回结果）。
Phase 5 才加入 Supervisor 和多 Agent 协调。

过早引入复杂性会拖慢迭代速度。

#### 原则 5：消息总线是最底层依赖

所有 Agent 之间、Agent 与 Supervisor 之间的通信，都经过消息总线。

```
当前：MemoryMessageBus（进程内，调试方便）    ← Phase 1 完成
当前：RedisMessageBus（分布式，多进程）       ← Phase 9 完成
切换方式：改一行配置（config.yaml message_bus.type）
```

### 0.5 Agent 协作模式

Lustre Agent 采用 **Supervisor 模式**，选择一个还是多个 Specialist 取决于任务复杂度。

```
┌─────────────────────────────────────────┐
│  Supervisor                             │
│  • 理解用户意图                         │
│  • 拆解任务（TaskPlanner）              │
│  • 选择 Agent                           │
│  • 分配任务                             │
│  • 聚合结果                             │
│  • 人工确认门（AWAITING_CONFIRMATION）  │
└─────────────────────────────────────────┘
         │
         │ MemoryMessageBus 或 RedisMessageBus
         ↓
┌─────────────────────────────────────────┐
│  SpecialistAgent × N                    │
│  code / research / test                 │
│  (ReActExecutor + LLM + Tools)          │
└─────────────────────────────────────────┘
```

为什么选这个模式：
- 单一入口，用户体验简单（只跟 Supervisor 说话）
- Supervisor 可以统筹全局（知道所有 Agent 在做什么）
- 比流水线模式（Pipeline）更灵活，Agent 之间可以有条件跳转

### 0.6 ReAct 循环

Agent 的核心执行循环是 **ReAct**（Reason + Act + Observe）：

```
while 未完成:
    1. Reason（推理）  →  LLM 分析当前状态，决定下一步
    2. Act（行动）     →  LLM 调用工具（读文件、搜索、运行命令）
    3. Observe（观察） →  工具返回结果
    4. Loop           →  结果注入上下文，LLM 继续推理
```

ReActExecutor 实现于 `lustre/models/executor.py`，所有 SpecialistAgent 共享。

### 0.7 术语表

| 术语 | 含义 |
|------|------|
| **Harness** | 模型之外的所有工程代码和配置 |
| **Model** | LLM（大语言模型），纯粹推理引擎 |
| **Agent** | Model + Harness = 可工作的智能体 |
| **Supervisor** | 协调 Agent，理解需求、拆解任务、分配工作 |
| **Specialist** | 专业 Agent（如 Code Agent），执行具体任务 |
| **ReAct** | 推理→行动→观察→循环的执行模式 |
| **Human-in-the-loop** | 人工确认介入，掌控关键决策节点 |
| **Message Bus** | Agent 间通信通道（Memory 或 Redis） |
| **Skill** | 可加载的 prompt 模板 + 元数据，增强 Agent 能力 |
| **ToolRegistry** | 中心化工具注册表，所有工具通过 `@register_tool` 装饰器注册 |

---

## 1. 概述

### 1.1 项目定位

**Lustre Agent** 是一个纯 Python 构建的多 Agent 个人编程助手系统。采用 Supervisor 模式：一个中心 Agent 协调多个专业 Agent 工作。每个专业 Agent 独立配置 LLM 模型、加载 Skill、调用工具。

以 CLI 交互模式运行，支持后台任务挂起，无 Web 界面。

### 1.2 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **语言** | Python 3.11+ | 要求 >= 3.11 |
| **构建工具** | uv | 极快的 Python 包管理器 |
| **打包** | pyproject.toml + hatchling | PEP 517/518 标准 |
| **代码格式** | ruff | 替代 flake8 + black + isort |
| **测试** | pytest | 52 个单元测试全部通过 |
| **CLI 美化** | Rich | 富文本输出、表格、面板、语法高亮 |
| **配置** | YAML + pydantic | YAML 人类可编辑，pydantic 校验类型 |
| **LLM 调用** | openai SDK + anthropic SDK | Provider 统一抽象 |
| **会话存储** | SQLite | 零配置，同步接口，FTS5 全文搜索 |
| **消息总线** | MemoryMessageBus / RedisMessageBus | 通过 `create_message_bus()` 一键切换 |

### 1.3 当前项目状态

```
Phase 0-9 全部完成 ✅
  ├── Phase 0: 项目骨架
  ├── Phase 1: 消息总线（Memory）
  ├── Phase 2: Agent 基类
  ├── Phase 3: Supervisor 状态机
  ├── Phase 4: LLM 集成（ReActExecutor）
  ├── Phase 5: Skill 系统
  ├── Phase 6: 内置工具（ToolRegistry + @register_tool）
  ├── Phase 7: Session 持久化（SQLite）
  ├── Phase 8: CLI 完善（Rich / /config / lustre_cli）
  └── Phase 9: Redis 消息总线

单元测试: 52 passed
CLI 命令: /help /skills /sessions /config /tools /go /abort /demo
```

---

## 2. 项目结构

### 2.1 整体目录

```
lustre-agent/
│
├── src/
│   ├── lustre/                    # 主包
│   │   ├── __init__.py
│   │   ├── __main__.py            # python -m lustre 入口
│   │   │
│   │   ├── cli.py                 # CLI 主脚本（交互循环）
│   │   │
│   │   ├── bus/                   # 消息总线
│   │   │   ├── __init__.py        # 导出 + create_message_bus()
│   │   │   ├── base.py            # MessageBus 抽象接口
│   │   │   ├── memory_bus.py      # 内存实现（Phase 1）
│   │   │   ├── redis_bus.py       # Redis Streams 实现（Phase 9）
│   │   │   └── message.py         # Message / MessageType 数据类
│   │   │
│   │   ├── models/                # LLM 层
│   │   │   ├── __init__.py
│   │   │   ├── client.py          # LLMClient 工厂（Anthropic/OpenAI）
│   │   │   └── executor.py        # ReActExecutor（Phase 4）
│   │   │
│   │   ├── agents/                # Agent 层
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # SpecialistAgent 基类
│   │   │   ├── code_agent.py      # CodeAgent（Phase 4）
│   │   │   └── echo_agent.py      # EchoAgent（Phase 2）
│   │   │
│   │   ├── supervisor/            # 协调层
│   │   │   ├── __init__.py
│   │   │   ├── supervisor.py      # Supervisor 主类
│   │   │   ├── state_machine.py   # 7 状态机
│   │   │   └── planner.py         # TaskPlanner（任务拆解）
│   │   │
│   │   ├── tools/                 # 工具系统
│   │   │   ├── __init__.py        # 导出 + 触发 builtin 自注册
│   │   │   ├── registry.py        # ToolRegistry 单例 + @register_tool
│   │   │   ├── access.py          # AgentToolPolicy（per-agent 工具过滤）
│   │   │   └── builtin/
│   │   │       ├── __init__.py
│   │   │       └── tools.py       # 5 工具（自注册）：read_file / write_file / patch / terminal / search_files
│   │   │
│   │   ├── skills/                # Skill 系统
│   │   │   ├── __init__.py
│   │   │   ├── manager.py         # SkillManager（发现/加载/匹配）
│   │   │   └── models.py          # Skill / SkillInstance 数据类
│   │   │
│   │   ├── session/               # 会话持久化（Phase 7）
│   │   │   ├── __init__.py
│   │   │   ├── store.py           # SessionStore（SQLite + FTS5 + WAL）
│   │   │   └── manager.py         # SessionManager（生命周期管理）
│   │   │
│   │   └── config/                # 配置管理
│   │       ├── __init__.py
│   │       └── loader.py          # Config 类（pydantic）+ create_bus()
│   │
│   └── lustre_cli/                # CLI 子命令工具
│       ├── __init__.py
│       ├── __main__.py            # python -m lustre_cli
│       ├── main.py                # argparse 入口（init / skills / config）
│       └── display.py             # Spinner / StatusBar / print_step
│
├── tests/
│   └── unit/
│       ├── bus/test_memory_bus.py
│       ├── agents/test_base.py
│       └── supervisor/test_state_machine.py
│
├── skills/                         # 内置 Skills（捆绑）
│   ├── python-expert/
│   │   └── SKILL.md
│   └── fastapi-expert/
│       └── SKILL.md
│
├── docs/
│   ├── architecture-design.md      # 本文档
│   ├── phase-0-*.md ... phase-9-*.md
│   └── ...
│
├── configs/
│   └── config.example.yaml
│
├── .env.example
├── pyproject.toml
└── uv.lock
```

### 2.2 目录规范说明

**为什么要用 `src/` 布局？**

| 对比 | src 布局 | 扁平布局 |
|------|---------|---------|
| `import lustre` | 始终是 installed package | 开发时可能 import 到本地目录 |
| 测试 | 测试永远不 import 源码目录 | 容易不小心直接 import `.py` 文件 |
| 分发 | 干净，src 就是源码 | 需要 `package-dir` 配置 |
| IDE | 原生支持 | 需要配置 source root |

**两个独立包：**
- `lustre` — 核心框架（Agent / Bus / Supervisor / Tools / Skills）
- `lustre_cli` — CLI 工具（init / skills install / config edit）

**测试目录 `tests/` 与 src 对应：**
- `tests/unit/bus/test_memory_bus.py` → 测试 `src/lustre/bus/memory_bus.py`
- pytest 自动发现，无需配置

**用户配置在 `~/.lustre/`（不提交 git）：**
- `~/.lustre/config.yaml` — 用户配置
- `~/.lustre/sessions.db` — SQLite 会话存储
- `~/.lustre/skills/` — 用户安装的 Skills

---

## 3. pyproject.toml 规范

```toml
[project]
name = "lustre-agent"
version = "0.9.0"
description = "Multi-Agent CLI assistant for coding"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "Eva"}]

dependencies = [
    "prompt_toolkit>=3.0.41",
    "rich>=13.7.0",
    "pyyaml>=6.0",
    "pydantic>=2.6.0",
    "python-dotenv>=1.0.0",
    "openai>=1.12.0",
    "anthropic>=0.18.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev   = ["ruff>=0.3.0", "mypy>=1.8.0", "pytest>=8.0.0", "pytest-cov>=4.1.0"]
redis = ["redis>=5.0.0"]
all   = ["lustre-agent[dev,redis]"]

[project.scripts]
lustre = "lustre.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/lustre", "src/lustre_cli"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

---

## 4. 核心模块详解

### 4.1 消息总线（bus/）

```
bus/
├── __init__.py      # create_message_bus("memory"|"redis")
├── base.py          # MessageBus ABC + Subscription
├── memory_bus.py    # threading + Queue 实现
├── redis_bus.py     # Redis Streams XADD/XREADGROUP 实现
└── message.py       # Message / MessageType / TaskRequest / TaskResult
```

**接口（两者完全一致）：**
```python
bus.publish(topic, message)           # 发布消息
sub = bus.subscribe(topic, callback)  # 订阅
bus.unsubscribe(sub)                   # 取消订阅
reply = bus.request(topic, message)    # 请求/响应（带超时）
```

**Redis Streams 键设计：**
```
lustre:stream:<topic>   — 消息流（如 lustre:stream:task.code）
lustre:reply:<msg_id>  — 临时回复流（request/response 用）
```

### 4.2 工具系统（tools/）

```
tools/
├── __init__.py       # 导出 ToolRegistry / @register_tool / get_all_tools
├── registry.py      # ToolRegistry 单例 + @register_tool 装饰器
├── access.py         # AgentToolPolicy（per-agent 工具过滤）
└── builtin/
    └── tools.py     # 5 工具（自注册）
```

**核心抽象：**
```python
@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict       # JSON Schema
    function: Callable     # 原始函数
    def invoke(self, args, task_id=None) -> ToolResult: ...
```

**自注册机制：**
```python
# tools/__init__.py
from lustre.tools.builtin import tools as _builtin  # 触发装饰器
from lustre.tools.registry import get_all_tools

# builtin/tools.py
@register_tool
def read_file(path: str, offset: int = 1, limit: int = 500, task_id=None):
    ...
```

**per-agent 工具过滤：**
```python
# AgentToolPolicy.DEFAULT_POLICY
{"code": None,  # 所有工具
 "research": ["read_file", "search_files"],
 "test": ["read_file", "search_files", "terminal"]}
```

### 4.3 Skill 系统（skills/）

```
skills/
├── __init__.py
├── manager.py    # SkillManager（发现/加载/匹配/注入）
└── models.py     # Skill / SkillInstance
```

**Skill 格式：**
```yaml
# SKILL.md
---
name: python-expert
description: Python 专家技能
version: 1.0.0
keywords: [python, pep8, typing, docstring]
---

# Python 专家指南

你是 Python 专家。以下是编写高质量 Python 代码的规范：

## 类型提示
...

## Docstring 格式
...
```

**匹配算法：** keyword 精确匹配（score × 1.0）+ TF-IDF cosine similarity（score × 2.0）

### 4.4 Session 系统（session/）

```
session/
├── __init__.py
├── store.py      # SessionStore（SQLite + FTS5 + WAL）
└── manager.py    # SessionManager（CRUD + 历史注入）
```

**SQLite Schema：**
```sql
sessions(id, title, created_at, updated_at, metadata)
messages(id, session_id, role, content, tool_call_id, tool_name, created_at)
CREATE INDEX idx_messages_session ON messages(session_id, created_at);
CREATE VIRTUAL TABLE messages_fts USING fts5(content, ...);
```

---

## 5. 环境配置规范

### 5.1 环境变量（.env.example）

```bash
# LLM API Keys（至少配置一个）
ANTHROPIC_API_KEY=sk-***
OPENAI_API_KEY=sk-***

# Redis（Phase 9 — 生产部署用，开发阶段可选）
REDIS_URL=redis://localhost:6379/0
```

### 5.2 配置文件（~/.lustre/config.yaml）

```yaml
version: "1.0"

model:
  provider: anthropic
  model: claude-sonnet-4-6
  api_key: ${ANTHROPIC_API_KEY}

agents:
  code:
    model_provider: anthropic
    model_name: claude-sonnet-4-6

tools:
  enabled:
    - read_file
    - write_file
    - patch
    - terminal
    - search_files

message_bus:
  type: memory   # "memory" 开发用；"redis" 生产用

session:
  db_path: ~/.lustre/sessions.db
```

### 5.3 消息总线切换

```python
# 方式 1：工厂函数
from lustre.bus import create_message_bus
bus = create_message_bus("redis", url="redis://localhost:6379/0")

# 方式 2：通过 Config
cfg = load_config()
bus = cfg.create_bus()  # 读取 config.yaml 的 message_bus.type
```

---

## 6. Supervisor 状态机

### 6.1 7 个状态

```
IDLE                  — 空闲，等待用户输入
  ↓
PLANNING              — 理解任务，调用 TaskPlanner 拆解
  ↓
AWAITING_CONFIRMATION — 等待用户确认（/go /accept）
  ↓
EXECUTING             — Agent 正在执行任务
  ↓
DONE                  — 任务完成
ABORTED               — 用户中止（/abort）
ERROR                 — 执行出错
```

### 6.2 状态转换图

```
                    /go
IDLE ───────────────────────────→ PLANNING
  ↑                                    │
  └────── /abort ──────────────────────┤
                                   (plan ready)
                                     ↓
                              AWAITING_CONFIRMATION
                               /go        ↓ /abort
                               ↓                  ↓
                          EXECUTING ─────→ DONE
                               ↓
                         (error) ↓
                               ERROR
```

---

## 7. CLI 命令参考

### 7.1 主 CLI（`python -m lustre` 或 `lustre`）

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有命令 |
| `/status` | 显示 Supervisor 当前状态 |
| `/go` | 确认计划，开始执行 |
| `/abort` | 中止当前任务 |
| `/skills` | 列出已加载的 Skills |
| `/skills load <name>` | 加载指定 Skill |
| `/skills unload <name>` | 卸载 Skill |
| `/skills match <text>` | 搜索最匹配的 Skill |
| `/sessions` | 列出所有会话 |
| `/sessions new <标题>` | 创建新会话 |
| `/sessions switch <id>` | 切换会话 |
| `/sessions delete <id>` | 删除会话 |
| `/sessions search <关键词>` | 全文搜索 |
| `/config` | 显示当前配置 |
| `/config edit` | 在 $EDITOR 中修改配置 |
| `/tools` | 列出所有可用工具 |
| `/demo` | Echo 模式演示 |

### 7.2 CLI 工具（`python -m lustre_cli`）

| 命令 | 说明 |
|------|------|
| `lustre init` | 初始化 `~/.lustre/` 目录 |
| `lustre skills list` | 显示 Skill 注册表 |
| `lustre skills install <name>` | 安装 Skill |
| `lustre config` | 在 $EDITOR 中打开配置 |

---

## 8. 各 Phase 交付物清单

| Phase | 核心文件 | 交付物 | 状态 |
|-------|---------|--------|------|
| **0** | `pyproject.toml`, `src/lustre/__init__.py` | 项目骨架 | ✅ |
| **1** | `bus/base.py`, `bus/memory_bus.py`, `bus/message.py` | MemoryMessageBus | ✅ |
| **2** | `agents/base.py`, `agents/echo_agent.py` | SpecialistAgent 基类 | ✅ |
| **3** | `supervisor/supervisor.py`, `supervisor/state_machine.py`, `supervisor/planner.py` | Supervisor 状态机 | ✅ |
| **4** | `models/client.py`, `models/executor.py`, `agents/code_agent.py` | ReActExecutor + CodeAgent | ✅ |
| **5** | `skills/manager.py`, `skills/models.py` | Skill 系统 | ✅ |
| **6** | `tools/registry.py`, `tools/access.py`, `tools/builtin/tools.py` | ToolRegistry + 5 工具 | ✅ |
| **7** | `session/store.py`, `session/manager.py` | SQLite 会话持久化 | ✅ |
| **8** | `cli.py`, `lustre_cli/` | Rich CLI + /config + lustre_cli | ✅ |
| **9** | `bus/redis_bus.py` | Redis Streams 总线 | ✅ |

---

## 9. 关键设计决策

### 为什么不选 LangGraph？

LangGraph 对状态机结构强约束。Supervisor 需要基于 LLM 输出做动态路由，LangGraph 对此处理不优雅。

### 为什么不选 CrewAI/AutoGen？

它们控制完整体验。定制 CLI、确认门、Skill 系统需要和框架对抗。在纯 Python 上从零构建更灵活。

### 为什么先走进程内 Agent（MemoryMessageBus）？

让所有 Agent 在同一进程内，调试方便（直接断点），迭代速度快。Redis 总线（Phase 9）是等核心逻辑稳定后才引入的。

### 为什么用 SQLite 做会话存储而不是 aiosqlite？

项目尚未引入 asyncio。直接用 `sqlite3`（同步）+ `threading.RLock()` 实现线程安全，避免异步复杂性。

### 为什么用 Redis Streams 而不是 Pub/Sub？

Pub/Sub 无持久性（消息发出即消失），Streams 支持消息持久化、回溯、消费者组负载均衡，更适合 Lustre Agent 的 request/response 模式。

### 为什么用 YAML 做配置？

人类可编辑，无需编译，支持环境变量 `${API_KEY}` 替换，pydantic 做类型校验。

### 为什么用 src/ 布局？

避免 import 混淆，测试始终走 installed package，IDE 支持好，PEP 723 推荐。

### 为什么用 uv？

2024 年 Python 包管理事实标准，比 pip 快 10-100x，依赖解析极快。

### 为什么用 @register_tool 装饰器？

工具定义和注册在同一个地方（`builtin/tools.py`），`import` 时自动触发注册，无需手动维护注册表。

### 为什么 ToolDef.invoke() 是统一调用接口？

原来各工具有各自的 `function(args, task_id)` 调用方式。统一到 `invoke()` 后，ToolRegistry 可以统一拦截、记录、过滤（AgentToolPolicy）所有工具调用。
