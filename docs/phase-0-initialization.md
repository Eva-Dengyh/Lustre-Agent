# Phase 0 — 项目初始化与骨架

> 日期: 2026-03-30
> 状态: ✅ 完成
> 目标: 搭建项目骨架，能 `uv run python -m lustre` 启动 CLI

---

## 1. 背景

Phase 0 是整个项目的起点，目标是建立一个符合开发规范、可运行、最小可用的骨架。
在此阶段不实现任何 Agent 逻辑，只确保：

- 目录结构规范（src 布局）
- 依赖管理正确（uv + pyproject.toml）
- CLI 能启动并交互（Rich 终端美化）
- 测试框架就绪（pytest + conftest）

---

## 2. 目标

1. 创建符合 PEP 723 / src 布局的目录结构
2. 编写 `pyproject.toml`，包含所有依赖和项目元数据
3. 创建最小可运行的 `src/lustre/` 包
4. 创建配置文件模板（config.example.yaml、.env.example）
5. `uv sync` 安装依赖
6. 验证 `uv run python -m lustre` 能启动并响应命令

---

## 3. 操作步骤

### 3.1 创建目录结构

```bash
mkdir -p src/lustre/{supervisor,agents,bus/models,skills,tools/builtin,session,config,utils}
mkdir -p tests/{unit/{bus,models,tools},integration}
mkdir -p scripts configs prompts
mkdir -p skills/python-best-practices/references
```

**说明：**

- `src/lustre/` 是主包，所有源码放在这里
- `tests/` 目录结构与 `src/` 对应，方便定位测试文件
- `skills/` 用于存放内置 Skills（Phase 6 才会用到）
- `configs/` 放配置模板文件

### 3.2 创建 pyproject.toml

文件路径: `pyproject.toml`

```toml
[project]
name = "lustre-agent"
version = "0.1.0"
description = "Multi-Agent CLI assistant for coding"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"

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
redis = ["redis>=5.0.0"]
all = ["lustre-agent[dev,redis]"]

[project.scripts]
lustre = "lustre.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/lustre"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
src = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**说明：**

- `name = "lustre-agent"` 决定包在 PyPI 上的名字和 pip install 的名字
- `[project.scripts]` 定义命令行入口，`lustre` 命令对应 `lustre.cli:main`
- `[tool.hatch.build.targets.wheel]` 告诉 hatchling 源码包在 `src/lustre`，这是 src 布局的关键配置
- `dev` 依赖单独放在 optional-dependencies，不污染生产环境
- `ruff` + `mypy` 作为代码质量工具，在 dev 组里

### 3.3 创建包初始化文件

#### 3.3.1 主包 `src/lustre/__init__.py`

```python
"""Lustre Agent — Multi-Agent CLI Programming Assistant."""

__version__ = "0.1.0"
__author__ = "Eva"
```

**说明：** 包的版本号统一在这里管理，其他模块通过 `from lustre import __version__` 获取。

#### 3.3.2 模块入口 `src/lustre/__main__.py`

```python
"""Entry point for: python -m lustre"""

from lustre.cli import main

if __name__ == "__main__":
    main()
```

**说明：** 实现 `python -m lustre` 启动方式。Python 运行一个模块时，`__name__` 会被设为 `__main__`，此时调用 `main()`。

#### 3.3.3 CLI 入口 `src/lustre/cli.py`

文件路径: `src/lustre/cli.py`

**核心功能：**

- Rich 终端美化（Banner 面板）
- prompt_toolkit 交互循环（未来版本）
- 当前版本：用 `console.input()` 实现简单 REPL
- 所有命令路由（`/help`、`/exit` 等）

**关键实现：**

```python
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

def print_banner() -> None:
    banner = Text()
    banner.append("Lustre Agent", style="bold gold1")
    banner.append(f"  v0.1.0", style="dim")
    panel = Panel(banner, title="Multi-Agent CLI Assistant",
                  border_style="gold1", expand=False)
    console.print(panel)

def main() -> None:
    print_banner()
    while True:
        try:
            user_input = console.input("\n[bold]>[/bold] ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]再见！[/yellow]")
            sys.exit(0)
        # 路由命令...
```

**说明：**

- `console.input()` 提供带样式的前缀提示符，比标准 `input()` 更美观
- `console.print()` 自动处理 Unicode 和颜色输出
- 用 `rich.panel.Panel` 做 Banner 边框，不需要手写 ASCII 边框
- 捕获 `KeyboardInterrupt`（Ctrl+C）和 `EOFError`（Ctrl+D）确保退出不报异常

#### 3.3.4 所有子包 `__init__.py`

以下文件全部是单行注释占位，不含任何逻辑：

```
src/lustre/supervisor/__init__.py    → "Supervisor — coordinates specialist agents."
src/lustre/agents/__init__.py        → "Specialist agents — code, test, research."
src/lustre/bus/__init__.py           → "Message bus — inter-agent communication."
src/lustre/bus/models/__init__.py    → "LLM model providers."
src/lustre/skills/__init__.py        → "Skill system — prompt templates and scripts."
src/lustre/tools/__init__.py         → "Built-in tools."
src/lustre/tools/builtin/__init__.py → "Built-in tool implementations."
src/lustre/session/__init__.py       → "Session persistence layer."
src/lustre/config/__init__.py        → "Configuration management."
```

**说明：** Python 要求一个目录是包（package）必须有 `__init__.py`。创建空文件占位，为未来代码留出结构。详细的模块说明写在文件内容的 docstring 里。

#### 3.3.5 测试子包 `__init__.py`

```
tests/__init__.py
tests/unit/__init__.py
tests/unit/bus/__init__.py
tests/unit/models/__init__.py
tests/unit/tools/__init__.py
tests/integration/__init__.py
```

**说明：** pytest 自动发现测试文件，这些 `__init__.py` 让测试目录结构完整。

### 3.4 创建配置文件模板

#### 3.4.1 `configs/config.example.yaml`

路径: `configs/config.example.yaml`

```yaml
system:
  name: "lustre-agent"
  version: "0.1.0"

agents:
  supervisor:
    model_provider: anthropic
    model_name: "claude-sonnet-4-6"
    api_key: "${ANTHROPIC_API_KEY}"

  code:
    model_provider: anthropic
    model_name: "claude-sonnet-4-6"
    api_key: "${ANTHROPIC_API_KEY}"
    skills: []
    confirmation_gates:
      after_code: true

  test:
    model_provider: anthropic
    model_name: "claude-sonnet-4-6"
    api_key: "${ANTHROPIC_API_KEY}"
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

**说明：**

- 配置用 YAML 格式，人类可读、可编辑
- `api_key: "${ANTHROPIC_API_KEY}"` 表示从环境变量读取，支持 `${VAR}` 语法
- `message_bus.type: memory` 是开发阶段配置，Phase 9 可改为 `redis`
- Phase 1-8 会逐步用到这个配置文件

#### 3.4.2 `.env.example`

路径: `.env.example`

```bash
# LLM API Keys — 至少配置一个
ANTHROPIC_API_KEY=sk-ant-xxxxx
OPENAI_API_KEY=sk-xxxxx
DEEPSEEK_API_KEY=sk-xxxxx
OPENROUTER_API_KEY=sk-or-xxxxx

# 可选：Redis（Phase 9 才需要）
REDIS_URL=redis://localhost:6379

# 日志级别
LOG_LEVEL=INFO
```

**说明：** `.env.example` 提交到 git，不含真实 API Key。用户复制为 `.env` 后填入真实 Key。

### 3.5 创建测试框架配置

路径: `tests/conftest.py`

```python
"""Pytest fixtures and configuration."""

import os
import sys
from pathlib import Path

import pytest

# Ensure src is on path
SRC_ROOT = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(SRC_ROOT))
```

**说明：** 将 `src/` 目录加入 Python 路径，确保 `from lustre import ...` 在测试中可用。`sys.path.insert(0, ...)` 优先级最高，避免 import 到本地目录的同名文件。

### 3.6 安装依赖并验证

```bash
cd /Users/eva/code/Lustre-Agent

# 1. 安装依赖（uv sync 读取 pyproject.toml）
uv sync

# 2. 验证 uv run python -m lustre 能启动
echo "/help
/exit" | uv run python -m lustre

# 3. 验证命令行入口也正常
echo "/exit" | uv run lustre
```

**uv sync 输出：**

```
Using CPython 3.11.15 interpreter
Creating virtual environment at: .venv
Resolved 43 packages in 764ms
Prepared 11 packages in 1.51s
Installed 27 packages in 54ms
  + lustre-agent==0.1.0 (from file:///.../Lustre-Agent)
  + rich==15.0.0
  + prompt-toolkit==3.0.52
  + pydantic==2.13.1
  + openai==2.32.0
  + anthropic==0.95.0
  + httpx==0.28.1
  + ...
```

**验证输出（`uv run python -m lustre`）：**

```
╭─ Multi-Agent CLI Assistant ─╮
│ Lustre Agent  v0.1.0        │
╰─────────────────────────────╯

>                      可用命令
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 命令                 ┃ 说明                     ┃
┡━━━━━━━━━━━━━━━━━━━━━━┇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ /help                │ 显示本帮助信息           │
│ /exit                │ 退出 CLI                 │
│ /new                 │ 开始新任务               │
│ ...                  │ ...                      │
└──────────────────────┴──────────────────────────┘

> 再见！
```

---

## 4. 目录结构

```
Lustre-Agent/
├── src/lustre/                      # 主包（src 布局）
│   ├── __init__.py                  # 包版本和说明
│   ├── __main__.py                  # python -m lustre 入口
│   ├── cli.py                       # CLI 主程序（Phase 0 交付物）
│   │
│   ├── supervisor/                   # 子包占位 __init__.py
│   ├── agents/
│   ├── bus/
│   │   └── models/
│   ├── skills/
│   ├── tools/
│   │   └── builtin/
│   ├── session/
│   ├── config/
│   └── utils/
│
├── tests/                           # 测试目录
│   ├── conftest.py                  # pytest 配置 + 路径设置
│   ├── unit/
│   │   ├── bus/
│   │   ├── models/
│   │   └── tools/
│   └── integration/
│
├── configs/
│   └── config.example.yaml          # 配置模板
│
├── scripts/                          # 运维脚本（未来）
├── prompts/                          # Agent 提示词（Phase 4+）
├── skills/                           # 内置 Skills（Phase 6）
├── docs/                             # 文档
│
├── pyproject.toml                    # 项目元数据 + 依赖
├── .env.example                      # 环境变量模板
├── .gitignore                        # 已存在
├── README.md
└── LICENSE
```

---

## 5. 遇到的问题与解决

### 5.1 uv sync 警告：VIRTUAL_ENV 不匹配

```
warning: `VIRTUAL_ENV=/Users/eva/code/hermes-agent/.venv` does not match
the project environment path `.venv` and will be ignored
```

**原因：** 终端环境中存在 `HERMES_AGENT` 的 venv，uv 检测到但忽略了它，在当前项目目录下创建了新的 `.venv`。

**解决：** 这是正常的预期行为，uv 会自动在每个项目目录下管理独立 venv，不影响使用。

---

## 6. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| uv 安装成功 | `uv --version` | 显示版本号 |
| 依赖安装成功 | `uv sync` | 无 error，所有包 installed |
| 模块可 import | `uv run python -c "from lustre import __version__; print(__version__)"` | 输出 0.1.0 |
| CLI 启动 | `echo "/exit" \| uv run python -m lustre` | Banner + "再见！" |
| 命令行入口 | `echo "/exit" \| uv run lustre` | 同上 |
| /help 命令 | `echo "/help\n/exit" \| uv run python -m lustre` | 显示帮助表格 |

---

## 7. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| pyproject.toml | `pyproject.toml` | 项目元数据，依赖声明 |
| CLI 程序 | `src/lustre/cli.py` | Phase 0 核心交付物 |
| 包初始化 | `src/lustre/__init__.py` | 版本号 |
| 模块入口 | `src/lustre/__main__.py` | `python -m lustre` 支持 |
| 配置模板 | `configs/config.example.yaml` | 供参考的配置 |
| 环境变量模板 | `.env.example` | API Key 模板 |
| pytest 配置 | `tests/conftest.py` | 测试路径配置 |
| 所有 `__init__.py` | 各子包目录 | 包结构占位 |

---

## 8. 下一步

Phase 0 ✅ 完成 → 进入 **Phase 1：消息总线（MemoryMessageBus）**

Phase 1 将实现：
- `lustre/bus/message.py` — Message 数据类
- `lustre/bus/base.py` — MessageBus 抽象接口
- `lustre/bus/memory_bus.py` — 内存消息总线实现
- 基本测试：pub / subscribe / request 功能验证
