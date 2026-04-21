---
day: 1
title: "起步 & Hello Agent"
status: done
est_minutes: 90
depends_on: []
---

# Day 1 · 起步 & Hello Agent

> **📖 阅读对象**
> - 人类读者：按顺序读；代码看"关键代码骨架"，细节自己补。
> - AI 模型：把本文当 spec —— 按「3. 目标产物」创建/修改文件，按「6. 验收」自证交付。

---

## 0. 30 秒速览

- **上一天终点**：空仓库
- **今天终点**：拥有一个可运行的 Python 项目，跑 `uv run lustre hello` 能拿到 LLM 的一句回复
- **新增能力**：LLM 可调用；项目骨架就位

## 1. 你将学到的概念（Why）

- **Agent Loop 的四要素**：LLM（决策）+ Tool（动作）+ Memory（上下文）+ Control Flow（流程） — 这是后续六天的核心主线
- **为什么用 uv**：速度快、锁文件稳、`uv run` 免去 venv 激活心智负担
- **第三方 Anthropic 兼容中转站**：统一走 `base_url + api_key` 形式；`langchain-anthropic` 的 `ChatAnthropic` 支持，但需注意 header 格式差异（见第 7 节）

```mermaid
flowchart LR
    user[用户输入] --> cli[CLI · Typer]
    cli --> llm[ChatAnthropic ← 中转站]
    llm --> cli --> user
```

本章只搭 **CLI → LLM** 这条最短链路；`Tool / Memory / Graph` 从 Day 2 开始加。

## 2. 前置条件

| 类别 | 要求 |
|---|---|
| 环境 | macOS / Linux / WSL；Python 3.11+；已安装 [uv](https://docs.astral.sh/uv/) |
| 账号 | 已有一个 Anthropic 兼容的第三方中转站账号（`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`） |
| 知识 | 会用 Python、基本 CLI；**不需要**预先懂 LangGraph |

## 3. 目标产物

```tree
Lustre-Agent/
├── pyproject.toml              ← 新增
├── uv.lock                     ← 新增（uv sync 自动生成）
├── .env.example                ← 已有
├── .env                        ← 你自己创建（gitignore 已排除）
├── src/lustre_agent/
│   ├── __init__.py             ← 新增
│   ├── cli.py                  ← 新增（Typer 入口）
│   ├── config.py               ← 新增（加载 .env）
│   └── llm.py                  ← 新增（ChatAnthropic 封装）
└── tests/
    ├── conftest.py             ← 新增（设置测试环境变量）
    └── day1_smoke.py           ← 新增
```

**依赖清单**（Day 1 需要）：

- `langchain-anthropic`
- `typer`
- `python-dotenv`
- `pydantic-settings`
- `pytest`（dev）

## 4. 实现步骤

### Step 1 — `pyproject.toml` 与入口点

- 定义包名 `lustre-agent`、Python 3.11+、依赖、console script `lustre = "lustre_agent.cli:app"`
- 运行 `uv sync` 生成锁文件

### Step 2 — `config.py` 加载 `.env`

- 用 `pydantic-settings` 的 `BaseSettings` 加载；暴露 `settings` 单例
- 必备字段：`anthropic_api_key`、`anthropic_base_url`、`model`（alias `lustre_model`）

### Step 3 — `llm.py` 封装 LLM 客户端

- 一个函数 `get_llm(model: str | None = None) -> ChatAnthropic`
- 默认读 `Settings.model`；允许调用方覆盖（为后面 Planner/Coder/Reviewer 各自用不同模型铺路）
- **关键**：通过 `default_headers` 传入 `Authorization: Bearer` 和正确的 `User-Agent`（见第 7 节）

### Step 4 — `cli.py` 搭 Typer

- `lustre hello` 子命令：调 `llm.invoke("Say hi in one sentence")`，打印到 stdout
- `lustre version` 子命令：打印版本号
- 为后续命令（`/code`, `/history` 等）留好扩展点

### Step 5 — smoke test

- `tests/conftest.py`：`os.environ.setdefault` 设好测试环境变量，避免 `pydantic-settings` 因缺少 key 报错
- `tests/day1_smoke.py`：
  - 能 import `lustre_agent.cli`
  - `get_llm()` 返回的对象具备 `invoke` 方法
  - 用 monkeypatch 注入 fake client，断言 `hello` 命令的行为

## 5. 关键代码骨架

```python
# src/lustre_agent/config.py
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env", "populate_by_name": True}

    anthropic_api_key: str
    anthropic_base_url: str = "https://api.anthropic.com"
    model: str = Field("claude-haiku-3", alias="lustre_model")

settings = Settings()
```

```python
# src/lustre_agent/llm.py
from langchain_anthropic import ChatAnthropic
from .config import settings

def get_llm(model: str | None = None) -> ChatAnthropic:
    return ChatAnthropic(
        model=model or settings.model,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_api_url=settings.anthropic_base_url,
        default_headers={
            # 中转站要求 Bearer 格式；Anthropic SDK 默认发 x-api-key，需覆盖
            "Authorization": f"Bearer {settings.anthropic_api_key}",
            # Poe API 等中转站会校验 User-Agent
            "User-Agent": "claude-code/2.1.78",
        },
    )
```

```python
# src/lustre_agent/cli.py
import typer
from .llm import get_llm

app = typer.Typer(help="Lustre Agent CLI")

@app.command()
def hello():
    """最小 LLM 调用演示"""
    llm = get_llm()
    response = llm.invoke("Say hi in one sentence")
    typer.echo(response.content)

@app.command()
def version():
    """显示版本信息"""
    typer.echo("lustre-agent 0.1.0")

if __name__ == "__main__":
    app()
```

```python
# tests/conftest.py
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
os.environ.setdefault("LUSTRE_MODEL", "claude-haiku-3")
```

```python
# tests/day1_smoke.py
def test_import_cli():
    from lustre_agent.cli import app
    assert app is not None

def test_get_llm_has_invoke():
    from lustre_agent.llm import get_llm
    llm = get_llm()
    assert hasattr(llm, "invoke")

def test_hello_command_with_mock(monkeypatch):
    from typer.testing import CliRunner
    from unittest.mock import MagicMock
    import lustre_agent.cli as cli_module

    fake_response = MagicMock()
    fake_response.content = "Hello! I'm your AI assistant."
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = fake_response
    monkeypatch.setattr(cli_module, "get_llm", lambda: fake_llm)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["hello"])
    assert result.exit_code == 0
    assert "Hello" in result.output
    fake_llm.invoke.assert_called_once_with("Say hi in one sentence")
```

## 6. 验收

### 6.1 手动

```bash
uv sync
cp .env.example .env   # 填入真实值（见下方 .env 格式）
uv run lustre hello
# 预期：打印一句 LLM 回复，如 "Hello!"
```

`.env` 格式：

```dotenv
ANTHROPIC_BASE_URL=https://api.poe.com   # 注意：不要带 /v1 后缀
ANTHROPIC_API_KEY=sk-poe-xxxxxxxx
LUSTRE_MODEL=claude-haiku-3              # 见第 7 节如何查询可用模型
```

### 6.2 自动

```bash
uv run pytest tests/day1_smoke.py -v
```

检查项：

- [x] `from lustre_agent.cli import app` 不报错
- [x] `get_llm()` 返回对象具备 `.invoke` 方法
- [x] `hello` 命令在 mock client 下能正常跑完

## 7. 常见坑 & FAQ

### Q: `422 - Missing required argument: authorization`

**A**：Anthropic SDK 默认把 key 放在 `x-api-key` 头，但许多第三方中转站（如 Poe API）要求 `Authorization: Bearer <key>` 格式。

在 `get_llm()` 里加 `default_headers` 覆盖即可：

```python
default_headers={"Authorization": f"Bearer {settings.anthropic_api_key}"}
```

### Q: `404 Not Found`（URL 路径翻倍）

**A**：Anthropic SDK 会自动在 `base_url` 后拼接 `/v1/messages`。如果 `ANTHROPIC_BASE_URL` 本身已含 `/v1`（如 `https://api.poe.com/v1`），最终变成 `.../v1/v1/messages`，导致 404。

**修复**：`ANTHROPIC_BASE_URL` 只写到域名，不带 `/v1`：

```dotenv
ANTHROPIC_BASE_URL=https://api.poe.com   # 正确
# ANTHROPIC_BASE_URL=https://api.poe.com/v1  ← 错误
```

### Q: `400 - Unsupported model`

**A**：中转站有自己的模型 ID，不能直接用 Anthropic 官方名称（如 `claude-3-5-sonnet-20241022`）。

查询中转站实际支持的模型：

```bash
source .env && curl -s "https://api.poe.com/v1/models" \
  -H "Authorization: Bearer $ANTHROPIC_API_KEY" | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)
# 只看支持 /v1/messages 的，按价格排序
models = [m for m in data['data'] if '/v1/messages' in m.get('supported_endpoints', [])]
for m in sorted(models, key=lambda x: float((x.get('pricing') or {}).get('prompt') or 99)):
    p = m.get('pricing') or {}
    print(f\"{m['id']:40s} prompt={p.get('prompt','?')}\")
"
```

Poe API 经过实测可用且最便宜的模型：`claude-haiku-3`

### Q: `uv run` 报找不到 `lustre`？

**A**：检查 `pyproject.toml` 里的 `[project.scripts]` 段是否写对；重新 `uv sync`。

### Q: 测试时报 `ValidationError: anthropic_api_key field required`？

**A**：`pydantic-settings` 在 import 时就会读取环境变量。在 `tests/conftest.py` 里用 `os.environ.setdefault` 提前设好 key，避免因缺少真实 key 导致测试失败。

## 8. 小结 & 下一步

- **今日核心**：搭好脚手架，验证 LLM 可调
- **你现在可以**：`uv run lustre hello`
- **明日（Day 2）预告**：引入 LangGraph，把"一次性调用"升级为"多轮对话 + 记忆 + 历史回放"

---

<details>
<summary>📎 AI 执行者的额外规则</summary>

1. 只创建「3. 目标产物」列出的文件。
2. 不要提前引入 `langgraph`，那是 Day 2 的事。
3. 用 `langchain-anthropic` 的 `ChatAnthropic`，不用 `langchain-openai`。
4. `default_headers` 里必须包含 `Authorization: Bearer` 和 `User-Agent`。
5. `ANTHROPIC_BASE_URL` 不带 `/v1` 后缀。
6. 交付完成须通过「6. 验收」的自动检查。

</details>
