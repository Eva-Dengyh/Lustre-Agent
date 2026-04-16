# Lustre Agent — 架构设计文档

> 版本: 0.2.0
> 作者: Eva
> 状态: 草稿
> 更新日期: 2026-03-30

---

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

我们在项目中每个模块对应的 Harness 角色：

| Harness 组件 | 对应项目模块 | Phase |
|--------------|------------|-------|
| **System Prompts** | `prompts/*.md` | Phase 4 |
| **Tools（工具描述）** | `lustre/tools/` + `prompts/*.md` | Phase 4 |
| **Bundled Infrastructure** | `lustre/bus/`（消息总线）、文件系统工具 | Phase 1 |
| **Orchestration Logic** | `lustre/supervisor/`（状态机、任务分配） | Phase 3 |
| **Hooks / Middleware** | `lustre/plugins/`（插件系统） | Phase 10 |
| **Durable Storage** | `lustre/session/`（SQLite） | Phase 8 |
| **Human-in-the-loop** | `lustre/supervisor/human_in_loop.py` | Phase 5 |

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

这不是过度设计，而是为未来留出扩展空间：
- 当前：MemoryMessageBus（进程内，调试方便）
- 未来：RedisMessageBus（分布式，多进程）
- 切换方式：改一行配置

### 0.5 Agent 协作模式

Lustre Agent 采用 **Supervisor 模式**，选择一个还是多个 Specialist 取决于任务复杂度。

```
┌─────────────────────────────────────────┐
│  Supervisor                             │
│  • 理解用户意图                         │
│  • 拆解任务                             │
│  • 选择 Agent                           │
│  • 分配任务                             │
│  • 聚合结果                             │
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

这是 Lustre Agent 所有 Agent 的底层执行逻辑，Phase 4 开始实现。

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
| **Message Bus** | Agent 间通信通道，本项目是消息总线的实现 |
| **Skill** | 可加载的 prompt 模板 + 脚本，增强 Agent 能力 |

---

## 1. 概述

### 1.1 项目定位

**Lustre Agent** 是一个纯 Python 构建的多 Agent 个人编程助手系统。采用 Supervisor 模式：一个中心 Agent 协调多个专业 Agent 工作。每个专业 Agent 独立配置 LLM 模型、加载 Skill、调用工具。

以 CLI 交互模式运行，支持后台任务挂起，无 Web 界面。

### 1.2 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **语言** | Python 3.11+ | 要求 >= 3.11，使用结构化模式匹配等新特性 |
| **构建工具** | uv | 极快的 Python 包管理器，替代 pip/poetry，2024 年主流选择 |
| **打包** | pyproject.toml | PEP 517/518 标准，所有元数据在此 |
| **类型检查** | mypy + pyright | 静态类型检查，保证代码质量 |
| **代码格式** | ruff | 替代 flake8 + black + isort，极快，2024 年事实标准 |
| **测试** | pytest + pytest-asyncio | pytest 是 Python 测试事实标准 |
| **CLI 输入** | prompt_toolkit | Hermes 在用，成熟稳定 |
| **终端美化** | Rich | 富文本输出、表格、面板、语法高亮 |
| **配置** | YAML + pydantic | YAML 人类可编辑，pydantic 校验类型 |
| **LLM 调用** | openai SDK + anthropic SDK | Provider 统一抽象 |
| **HTTP** | httpx | 同步/异步 HTTP，OpenAI SDK 内部使用 |
| **会话存储** | SQLite (aiosqlite) | 零配置，异步支持 |
| **消息总线** | 内存（开发）/ Redis（生产） | 开发阶段用 threading.Queue，生产切换 Redis |

---

## 2. 项目结构

### 2.1 整体目录

```
lustre-agent/
│
├── src/                          # 源代码（PEP 723 推荐的 src 布局）
│   └── lustre/                   # 主包
│       ├── __init__.py          # 包初始化，版本在这里
│       ├── __main__.py          # python -m lustre 入口
│       │
│       ├── cli.py                # CLI 入口脚本（bin/ 风格）
│       │
│       ├── supervisor/           # Supervisor 协调层
│       │   ├── __init__.py
│       │   ├── agent.py         # Supervisor Agent
│       │   ├── task_planner.py  # 任务拆解
│       │   ├── human_in_loop.py # 人工确认交互
│       │   └── state.py         # 状态机定义
│       │
│       ├── agents/               # 专业 Agent 层
│       │   ├── __init__.py
│       │   ├── base.py          # SpecialistAgent 基类
│       │   ├── code_agent.py    # 代码编写
│       │   ├── test_agent.py    # 测试验证
│       │   ├── research_agent.py # 技术调研
│       │   └── echo_agent.py    # 开发阶段用的模拟 Agent
│       │
│       ├── bus/                  # 消息总线层
│       │   ├── __init__.py
│       │   ├── base.py          # MessageBus 抽象接口
│       │   ├── memory_bus.py    # 内存实现（开发用）
│       │   ├── redis_bus.py     # Redis 实现（生产用）
│       │   └── message.py      # Message / TaskPayload 数据类
│       │
│       ├── models/               # LLM 模型层
│       │   ├── __init__.py
│       │   ├── client.py        # LLMClient 工厂
│       │   └── providers/       # Provider 具体实现
│       │       ├── __init__.py
│       │       ├── openai_like.py
│       │       └── anthropic.py
│       │
│       ├── skills/               # Skill 系统
│       │   ├── __init__.py
│       │   ├── loader.py        # SkillLoader
│       │   ├── registry.py      # Skill 注册表
│       │   └── models.py        # Skill 数据类
│       │
│       ├── tools/                # 工具系统
│       │   ├── __init__.py
│       │   ├── registry.py      # ToolRegistry
│       │   └── builtin/         # 内置工具
│       │       ├── __init__.py
│       │       ├── terminal.py
│       │       ├── file_ops.py
│       │       └── web_search.py
│       │
│       ├── session/             # 会话持久化
│       │   ├── __init__.py
│       │   └── store.py         # SessionStore
│       │
│       ├── config/              # 配置管理
│       │   ├── __init__.py
│       │   └── loader.py        # YAML 配置加载
│       │
│       └── utils/               # 公共工具
│           ├── __init__.py
│           └── logging.py       # 日志配置
│
├── tests/                        # 测试（与 src 结构对应）
│   ├── __init__.py
│   ├── conftest.py              # pytest fixtures
│   │
│   ├── unit/                    # 单元测试
│   │   ├── __init__.py
│   │   ├── bus/
│   │   │   ├── __init__.py
│   │   │   ├── test_memory_bus.py
│   │   │   └── test_message.py
│   │   ├── models/
│   │   │   └── __init__.py
│   │   └── tools/
│   │       └── __init__.py
│   │
│   └── integration/             # 集成测试
│       ├── __init__.py
│       ├── test_supervisor_flow.py
│       └── test_agent_pipeline.py
│
├── scripts/                      # 工具脚本
│   ├── bootstrap.sh             # 项目初始化脚本
│   └── run_tests.sh             # 测试运行脚本
│
├── docs/                        # 文档
│   ├── architecture-design.md   # 本文档
│   └── ...
│
├── configs/                     # 配置文件模板
│   ├── config.example.yaml      # 配置示例
│   └── config.development.yaml  # 开发配置
│
├── prompts/                     # Agent 系统提示词
│   ├── supervisor.md
│   ├── code_agent.md
│   ├── test_agent.md
│   └── research_agent.md
│
├── skills/                      # 内置 Skills
│   └── python-best-practices/
│       ├── SKILL.md
│       └── references/
│
├── .env.example                 # 环境变量模板
├── .gitignore
│
├── pyproject.toml               # 项目元数据 + 构建配置
├── uv.lock                      # 依赖锁文件（uv 生成）
│
├── README.md
└── LICENSE
```

### 2.2 目录规范说明

**为什么要用 `src/` 布局？**

| 对比 | src 布局 | 扁平布局 |
|------|---------|---------|
| `import lustre` | 始终是 installed package | 开发时可能 import 到本地目录 |
| 测试 | 测试永远不 import 源码目录 | 容易不小心直接 import `.py` 文件 |
| 分发 | 干净，src 就是源码 | 需要 `package-dir` 配置 |
| IDE | 原生支持 | 需要配置 source root |

**包名统一为 `lustre`**
- 源码在 `src/lustre/`
- 所有 import 写 `from lustre.bus import ...`
- 安装后使用 `python -m lustre` 或 `lustre` 命令

**测试目录 `tests/` 与 src 对应**
- `tests/unit/bus/test_memory_bus.py` → 测试 `src/lustre/bus/memory_bus.py`
- `tests/integration/test_supervisor_flow.py` → 集成测试
- pytest 自动发现，无需配置

**配置文件分类**
- `configs/config.example.yaml` — 提交到 git，示格式
- `.env.example` — 环境变量模板，不含敏感值
- 用户实际配置放在 `~/.lustre/config.yaml`（不提交 git）

**scripts/ 放运维脚本**
- 不属于包代码，但是项目一部分
- bootstrap.sh：新建项目时初始化目录
- run_tests.sh：本地跑测试的便捷脚本

---

## 3. pyproject.toml 规范

```toml
[project]
name = "lustre-agent"
version = "0.1.0"
description = "Multi-Agent CLI assistant for coding"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [
    {name = "Eva", email = "eva@example.com"}
]
keywords = ["ai", "agent", "cli", "coding", "multi-agent"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Software Development :: Libraries :: Python Modules",
]

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
dev = [
    "ruff>=0.3.0",
    "mypy>=1.8.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
]
redis = [
    "redis>=5.0.0",
]
all = [
    "lustre-agent[dev,redis]",
]

[project.scripts]
lustre = "lustre.cli:main"

[project.urls]
Homepage = "https://github.com/yourname/lustre-agent"
Repository = "https://github.com/yourname/lustre-agent"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/lustre"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "W",     # pycodestyle warnings
    "F",     # Pyflakes
    "I",     # isort
    "UP",    # pyupgrade
    "B",     # flake8-bugbear
    "C4",    # flake8-comprehensions
    "RUF",   # Ruff-specific rules
]
ignore = [
    "E501",  # line too long (handled by formatter)
    "B008",  # do not perform function calls in argument defaults
]

[tool.mypy]
python_version = "3.11"
src = ["src"]
test = ["tests"]
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"

[tool.coverage.run]
source = ["src/lustre"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

---

## 4. 技术选型详细说明

### 4.1 为什么用 uv 而不是 pip / poetry？

| 对比项 | pip | poetry | uv |
|--------|-----|--------|-----|
| 安装速度 | 慢 | 中 | **极快**（Rust 实现） |
| 锁文件 | requirements.txt | poetry.lock | uv.lock |
| 依赖解析 | 慢 | 中 | **极快** |
| Python 版本管理 | 手动 | pyenv | 内置 |
| 2024 年流行度 | 高（惯性） | 高 | **快速上升** |
| PEP 517 支持 | 一般 | 好 | **原生** |

**结论**：uv 是 2024 年 Python 生态最大的效率提升，选它没有争议。

安装方式：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 4.2 为什么用 ruff 而不是 flake8 + black？

| 对比 | 分别用 | ruff |
|------|--------|------|
| 速度 | flake8 + black + isort = 慢 | **一个工具，快 10-100x** |
| 配置 | 三份配置 | **一份** |
| 维护 | 三个项目 | **一个** |
| 功能 | 各司其职 | **全覆盖** |

**结论**：ruff 2023-2024 年已是 Python 代码质量工具的事实标准，直接用。

### 4.3 为什么用 pydantic 做配置校验？

- YAML 加载后无类型，pydantic 做运行时校验
- 配置字段有类型提示，IDE 自动补全
- 自动环境变量注入（`Field(default=...)`）
- 验证失败有清晰的错误信息

```python
from pydantic import BaseModel, Field
from typing import Optional

class AgentConfig(BaseModel):
    model_provider: str = Field(..., description="e.g. openai_like, anthropic")
    model_name: str = Field(..., description="e.g. claude-sonnet-4-6")
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
```

### 4.4 为什么不用 FastAPI / 任何 Web 框架？

项目目标是 CLI 工具，不做 HTTP 服务。prompt_toolkit 足够处理交互。强行引入 FastAPI 会增加不必要的复杂度。

### 4.5 为什么用 Rich 而不是基本 print？

- **Panel** — 分组展示信息
- **Table** — 格式化表格
- **Syntax** — 代码语法高亮
- **Status** — 实时状态显示
- **Progress** — 进度条

CLI 工具的用户体验很大程度取决于输出美观程度，Rich 是 Python 终端美化的最优解。

---

## 5. 环境配置规范

### 5.1 环境变量（.env.example）

```bash
# LLM API Keys（至少配置一个）
ANTHROPIC_API_KEY=sk-ant-xxxxx
OPENAI_API_KEY=sk-xxxxx
DEEPSEEK_API_KEY=sk-xxxxx
OPENROUTER_API_KEY=sk-or-xxxxx

# 可选：Redis（阶段 9 才需要）
REDIS_URL=redis://localhost:6379

# 日志级别
LOG_LEVEL=INFO
```

### 5.2 用户配置（~/.lustre/config.yaml）

```yaml
system:
  name: "lustre-agent"
  version: "0.1.0"

agents:
  supervisor:
    model_provider: anthropic
    model_name: "claude-sonnet-4-6"

  code:
    model_provider: openai_like
    model_name: "claude-sonnet-4-6"
    base_url: "https://api.anthropic.com/v1"
    api_key: "${ANTHROPIC_API_KEY}"
    skills:
      - python-best-practices

  test:
    model_provider: openai_like
    model_name: "deepseek/deepseek-chat-v3"
    base_url: "https://api.deepseek.com/v1"
    api_key: "${DEEPSEEK_API_KEY}"
    auto_run: true

  research:
    model_provider: anthropic
    model_name: "claude-sonnet-4-6"
    api_key: "${ANTHROPIC_API_KEY}"

message_bus:
  type: memory
  redis_url: "redis://localhost:6379"
  max_hops: 10
  request_timeout: 300

skills_dir: "~/.lustre/skills"
session_dir: "~/.lustre/sessions"
log_dir: "~/.lustre/logs"

tools:
  terminal:
    enabled: true
    timeout: 60
  web_search:
    enabled: true
```

---

## 6. 开发规范

### 6.1 Git 分支模型

```
main          — 稳定版本，始终可发布
develop       — 开发分支，下一版本的集成分支
feat/xxx      — 功能分支
fix/xxx       — 修复分支
docs/xxx      — 文档分支
```

- 功能开发从 `develop` 分支开 `feat/`
- 修复从 `main` 或 `develop` 开 `fix/`
- Merge 前必须通过所有测试

### 6.2 Commit 规范

格式：`type: 简短描述`

```
feat: 新增 Research Agent 技术调研能力
fix: 修复 MemoryMessageBus 并发时丢失消息问题
docs: 更新架构设计文档 Phase 3 说明
refactor: 重构 Agent 基类，提取公共方法
test: 新增 Supervisor 状态机单元测试
chore: 升级 ruff 到 0.3.0
```

type 类型：feat / fix / docs / refactor / test / chore / perf / ci

### 6.3 代码规范

**格式化**
```bash
uv ruff format .
```

**类型检查**
```bash
uv mypy src/
```

**全部检查**
```bash
uv ruff check src/
uv mypy src/
uv pytest tests/
```

**Git pre-commit hook（推荐）**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: ruff-format
        name: ruff format
        entry: uv ruff format
        language: system
        types: [python]
      - id: ruff-check
        name: ruff check
        entry: uv ruff check
        language: system
        types: [python]
      - id: mypy
        name: mypy
        entry: uv mypy
        language: system
        types: [python]
```

### 6.4 发布规范

```bash
# 1. 更新版本号（手动在 pyproject.toml）
# 2. 生成 changelog
# 3. 打 tag
git tag -a v0.1.0 -m "v0.1.0: first usable version"
git push origin main --tags

# 4. 构建并发布（未来）
uv build
uv publish
```

---

## 7. 文件编码与格式

- **所有源码**：UTF-8，无 BOM
- **换行符**：LF（Unix 风格），`.gitattributes` 控制
- **缩进**：4 空格（Python 标准），ruff + black 自动处理
- **行长度**：最大 100 字符（ruff default）

```bash
# .gitattributes
* text=auto
*.py text eol=lf
*.md text eol=lf
*.yaml text eol=lf
*.toml text eol=lf
```

---

## 8. 项目初始化流程

新建项目时的标准操作：

```bash
# 1. 创建项目目录
mkdir lustre-agent && cd lustre-agent

# 2. 初始化 uv 项目
uv init --name lustre-agent --python 3.11

# 3. 安装依赖
uv add prompt_toolkit rich pyyaml pydantic python-dotenv openai anthropic httpx
uv add --group dev ruff mypy pytest pytest-asyncio pytest-cov

# 4. 创建目录结构
mkdir -p src/lustre/{supervisor,agents,bus/models,skills,tools/builtin,session,config,utils}
mkdir -p tests/{unit/{bus,models,tools},integration}
mkdir -p scripts docs configs prompts skills

# 5. 配置 git
git init
cp configs/.gitattributes .gitattributes

# 6. 安装 pre-commit
uv add --group dev pre-commit
uv run pre-commit install

# 7. 写最小代码，跑通测试
# （从 Phase 0 开始）
```

---

## 9. 测试策略

### 9.1 测试分层

```
tests/
├── unit/                    # 单元测试（每个模块独立测试）
│   ├── bus/
│   │   └── test_memory_bus.py
│   └── models/
│       └── test_client.py
│
├── integration/              # 集成测试（多模块协作）
│   ├── test_supervisor_flow.py
│   └── test_agent_pipeline.py
│
└── conftest.py              # pytest fixtures 共享
```

### 9.2 单元测试规范

- 每个测试函数以 `test_` 开头
- 一个测试只验证一个行为
- mock 外部依赖（LLM API、文件系统）
- 测试文件放在对应模块的 `tests/` 子目录下

### 9.3 集成测试规范

- 不 mock LLM，用 fake model 或 recorded responses
- 测试完整的用户流程
- 在 `tests/integration/` 下

### 9.4 CI 基础（GitHub Actions）

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv install --group dev
      - run: uv ruff check src/
      - run: uv mypy src/
      - run: uv pytest tests/ --cov --cov-report=xml
      - uses: codecov/codecov-action@v4
```

---

## 10. 各阶段交付物清单

| 阶段 | 核心文件 | 交付物 |
|------|---------|--------|
| **Phase 0** | `pyproject.toml`, `src/lustre/__init__.py` | 项目骨架，可 `uv run python -m lustre` |
| **Phase 1** | `src/lustre/bus/base.py`, `memory_bus.py`, `message.py` | 消息总线，跑通 pub/sub |
| **Phase 2** | `src/lustre/agents/base.py`, `echo_agent.py` | Agent 基类，可收发任务 |
| **Phase 3** | `src/lustre/supervisor/agent.py`, `state.py` | Supervisor 骨架，状态机 |
| **Phase 4** | `src/lustre/models/client.py`, `tools/registry.py`, `code_agent.py` | 单 Agent 接 LLM + 工具 |
| **Phase 5** | `research_agent.py`, `test_agent.py`, `human_in_loop.py` | 完整流水线 + 确认门 |
| **Phase 6** | `skills/loader.py`, `skills/models.py`, `prompts/*.md` | Skill 系统 |
| **Phase 7** | `cli.py`（完整版） | 完整 CLI，所有命令 |
| **Phase 8** | `session/store.py` | 会话持久化 |
| **Phase 9** | `bus/redis_bus.py` | Redis 总线（可选） |
| **Phase 10** | `plugins/hook_system.py` | 插件系统（可选） |

---

## 11. 关键设计决策

### 为什么不选 LangGraph？

LangGraph 对状态机结构强约束。Supervisor 需要基于 LLM 输出做动态路由，LangGraph 对此处理不优雅。

### 为什么不选 CrewAI/AutoGen？

它们控制完整体验。定制 CLI、确认门、Skill 系统需要和框架对抗。在 Hermes 模式上扩展更灵活。

### 为什么先走进程内 Agent？

MemoryMessageBus 让所有 Agent 在同一进程内，调试方便（直接断点），迭代速度快。

### 为什么用 SQLite 做会话存储？

零配置、零依赖。aiosqlite 提供异步支持，对个人使用足够。

### 为什么用 YAML 做配置？

人类可编辑，无需编译，支持环境变量 `${API_KEY}` 替换，pydantic 做类型校验。

### 为什么用 src/ 布局？

避免 import 混淆，测试始终走 installed package，IDE 支持好，PEP 723 推荐。

### 为什么用 uv？

2024 年 Python 包管理事实标准，比 pip 快 10-100x，依赖解析极快。
