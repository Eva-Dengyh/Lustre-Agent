# Lustre Agent

> Multi-Agent CLI 编程助手 — 帮你协调多个专业 Agent 完成开发任务

---

## 什么是 Lustre Agent

Lustre Agent 是一个纯 Python 构建的多 Agent 编程助手，采用 Supervisor 模式运行：

```
       [你]
         │
         ▼
   ┌───────────┐
   │ Supervisor │  ←── 理解需求、拆解任务、协调 Agent、人工确认
   └─────┬─────┘
         │
    ┌────┼────┐
    ▼    ▼    ▼
 [调研] [代码] [测试]   ←── 专业 Agent 各司其职
```

**核心特点：**
- **Supervisor 协调** — 一个 Agent 总负责，理解需求、拆解步骤、分配任务
- **人机协同** — 每个阶段完成后等你确认再继续，掌控感始终在你
- **多模型支持** — 每个 Agent 可独立选择模型（Claude、DeepSeek、MiniMax 等）
- **Skill 可扩展** — 加载 prompt 模板和脚本，像 Hermes 一样可定制
- **纯 CLI** — 无 Web 界面，终端里直接跑
- **后台任务** — 长时任务挂后台，不阻塞终端

---

## 工作流程

```
你: "帮我调研 FastAPI 和 Flask，然后写一个 hello world API"

        ↓
[Supervisor] 分析需求，给出计划

        ↓
⚠️ 确认计划
  任务拆解：调研技术方案 → 编写代码 → 运行测试
  Agent 安排：
    调研 Agent → 分析 FastAPI vs Flask
    代码 Agent  → 编写 hello world API
    测试 Agent  → 验证代码正确性

  (/go 继续 /edit 修改 /abort 取消)

        ↓
[调研 Agent] 搜索对比 FastAPI vs Flask，给出建议

        ↓
⚠️ 确认技术选型
  推荐: FastAPI（现代、类型安全、原生异步）
  备选: Flask（简单、生态成熟）

  (/accept /modify /reject)

        ↓
[代码 Agent] 写 FastAPI hello world

        ↓
[测试 Agent] 运行测试

        ↓
✅ 完成：代码 + 测试报告
```

**核心原则：每个 Agent 执行前都需要你确认，掌控感始终在你手里。**

---

## 安装

### 前置要求

- Python 3.11+
- uv（Python 包管理器）

```bash
# 如果没有 uv，安装它
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 安装 Lustre Agent

```bash
# 克隆项目
git clone https://github.com/yourname/lustre-agent.git
cd lustre-agent

# 安装依赖
uv sync

# 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 配置

创建 `~/.lustre/config.yaml`：

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

  test:
    model_provider: openai_like
    model_name: "deepseek/deepseek-chat-v3"
    base_url: "https://api.deepseek.com/v1"
    api_key: "${DEEPSEEK_API_KEY}"

  research:
    model_provider: anthropic
    model_name: "claude-sonnet-4-6"
    api_key: "${ANTHROPIC_API_KEY}"

message_bus:
  type: memory
```

---

## 快速开始

```bash
cd lustre-agent

# 激活虚拟环境
source .venv/bin/activate

# 启动 CLI
python -m lustre

# 或用 uv 直接跑
uv run python -m lustre
```

### 交互示例

```
$ lustre

╔══════════════════════════════════════╗
║         Lustre Agent v0.1.0         ║
╚══════════════════════════════════════╝

[lustre] 启动中...
[lustre] Supervisor 就绪

> 帮我写一个 FastAPI 用户认证接口

📋 计划：research → code → test

  1. [调研] 分析技术方案
  2. [代码] 编写认证接口
  3. [测试] 运行单元测试

  输入 /go 继续，/edit 修改计划，/abort 取消

> /go

[调研 Agent] 分析中...
💡 技术建议: JWT + bcrypt

⚠️ 确认技术方案？
  /accept  — 使用推荐方案继续
  /modify  — 修改方案
  /reject  — 放弃调研阶段

> /accept

[代码 Agent] 编写中...
  ✏️ 写入: auth.py
  ✏️ 写入: schemas.py

[测试 Agent] 运行测试中...
  ✅ test_login_success       PASS
  ✅ test_register_duplicate   PASS

══════════════════════════════════════
✅ 任务完成

产物：
  auth.py    (用户认证核心逻辑)
  schemas.py (Pydantic 模型)

> /exit
再见！
```

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/new` | 开始新任务 |
| `/status` | 查看当前任务状态 |
| `/go` | 通过当前确认门，继续执行 |
| `/abort` | 取消当前任务 |
| `/retry` | 重试失败的上一步 |
| `/skip` | 跳过当前步骤 |
| `/edit` | 修改计划或任务描述 |
| `/bg` | 挂起任务到后台 |
| `/jobs` | 列出所有后台任务 |
| `/kill <id>` | 终止后台任务 |
| `/exit` | 退出 CLI |

---

## 项目结构

```
lustre-agent/
├── src/
│   └── lustre/
│       ├── supervisor/        # Supervisor 协调层
│       ├── agents/            # 专业 Agent（Code/Test/Research）
│       ├── bus/               # 消息总线
│       ├── models/            # LLM 调用封装
│       ├── skills/            # Skill 系统
│       ├── tools/             # 内置工具
│       ├── session/           # 会话持久化
│       └── config/            # 配置加载
├── tests/                     # 测试
├── configs/                   # 配置模板
├── prompts/                   # Agent 系统提示词
├── skills/                    # 内置 Skills
└── docs/
    └── architecture-design.md  # 架构设计文档
```

---

## 开发指南

```bash
# 安装 uv（如果还没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步依赖
uv sync

# 安装 pre-commit hook
uv run pre-commit install

# 格式化代码
uv run ruff format .

# 代码检查
uv run ruff check .

# 类型检查
uv run mypy src/

# 运行测试
uv run pytest

# 全部检查
uv run ruff format && uv run ruff check && uv run mypy src/ && uv run pytest
```

---

## 实现阶段

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 0 | 🔨 进行中 | 项目初始化、骨架 |
| Phase 1 | 📋 待开始 | 消息总线（MemoryMessageBus） |
| Phase 2 | 📋 待开始 | Agent 基类（不含 LLM） |
| Phase 3 | 📋 待开始 | Supervisor 状态机 |
| Phase 4 | 📋 待开始 | 接 LLM，单 Agent 运行 |
| Phase 5 | 📋 待开始 | 完整流水线 + 人工确认 |
| Phase 6 | 📋 待开始 | Skill 系统 |
| Phase 7 | 📋 待开始 | CLI 完善 |
| Phase 8 | 📋 待开始 | 会话持久化 |
| Phase 9 | 📋 可选 | Redis 总线（分布式） |
| Phase 10 | 📋 可选 | 插件系统 |

---

## 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 包管理 | uv | 2024 年事实标准，比 pip 快 100x |
| 代码格式 | ruff | 替代 black+flake8+isort，一个工具 |
| 类型检查 | mypy + pydantic | 静态 + 运行时双重保障 |
| CLI | prompt_toolkit | 交互式 CLI 成熟方案 |
| 终端美化 | Rich | 表格、面板、语法高亮 |
| 配置 | YAML + pydantic | 人类可编辑 + 类型校验 |
| 会话存储 | SQLite | 零配置，个人使用足够 |

---

## License

MIT
