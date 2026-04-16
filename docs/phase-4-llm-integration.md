# Phase 4 — 接 LLM，单 Agent 运行

> 日期: 2026-04-16
> 状态: ✅ 完成
> 目标: 将 LLM 接入 CodeAgent，实现"自然语言需求 → 代码生成"全流程

---

## 1. 背景

Phase 3 建立了 Supervisor + Planner 的协调框架，但 Agent 是 EchoAgent（只返回固定字符串）。Phase 4 的目标是用真正的 LLM 替换 EchoAgent，让 CodeAgent 能：
1. 理解任务描述
2. 调用工具（读文件、写文件、执行命令）
3. 迭代验证，直到任务完成

**参考文档：** `docs/architecture-design.md` 第 0 节（核心公式：Agent = Model + Harness）

---

## 2. 目标

1. 实现 `ModelClient` 抽象层，支持 Anthropic + OpenAI
2. 实现 `ReActExecutor`，驱动 Reason → Act → Observe 循环
3. 实现内置工具集（read_file / write_file / patch / terminal / search_files）
4. 实现 `CodeAgent`，整合 LLM + 工具
5. 实现 `ConfigLoader`，从 YAML 加载配置（支持 `${ENV_VAR}` 替换）
6. 更新 CLI，支持 Echo / LLM 两种模式
7. 52 个单元测试，全部通过

---

## 3. 操作步骤

### 3.1 ConfigLoader

文件路径: `src/lustre/config/loader.py`

```python
# 支持 ${VAR} 和 ${VAR:default} 替换
cfg = load_config()
cfg.agents["code"]["model_name"]  # "claude-sonnet-4-6"
```

配置搜索顺序：
1. `LUSTRE_CONFIG` 环境变量
2. `./configs/config.yaml`
3. `./configs/config.example.yaml`（开发回退）
4. `~/.lustre/config.yaml`

**Bug 修复：** 最初使用 `@cached_property` + `__slots__`，两者不兼容（`cached_property` 需要 `__dict__`）。改为显式惰性属性（`_system = None`，按需初始化）。

### 3.2 ModelClient 抽象层

文件路径: `src/lustre/models/client.py`

```
                    ┌─────────────────┐
                    │  ModelClient    │  ← 抽象接口
                    │  .chat(...)     │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
    ┌─────────────────┐            ┌─────────────────┐
    │ AnthropicClient │            │  OpenAIClient   │
    │ (Claude SDK)    │            │  (GPT-4o, o3)  │
    └─────────────────┘            └─────────────────┘
```

接口统一返回格式：
```python
{
    "content": str,           # 文本响应
    "tool_calls": list[dict], # [{"id", "name", "arguments": dict}]
    "stop_reason": str,       # "end_turn" | "max_tokens" | "tool_use"
    "usage": dict,            # {input_tokens, output_tokens, total_tokens}
}
```

### 3.3 ReActExecutor

文件路径: `src/lustre/models/executor.py`

ReAct 循环是 Agent 的核心执行引擎：

```
while 未达到 max_iterations:
    1. LLM 推理 → 决定调用哪个工具（或返回最终答案）
    2. 执行工具 → 返回结果
    3. 观察结果 → 注入到上下文，LLM 继续推理
```

```python
executor = ReActExecutor(
    client=anthropic_client,
    system_prompt=SYSTEM_PROMPT,
    tools=[read_file_tool, write_file_tool, ...],
    max_iterations=20,
)
answer, trace = executor.execute("写一个 FastAPI hello world")
```

**关键设计：**
- `ExecutionTrace` 记录每一步推理，用于调试
- 工具 schema 由 `_tool_to_schema()` 转换为 provider 格式
- `ToolResult.content` 自动把各种返回值格式化为字符串

### 3.4 内置工具集

文件路径: `src/lustre/tools/builtin/tools.py`

Phase 4 直接实现，不等 Phase 6：

| 工具 | 功能 |
|------|------|
| `read_file` | 读取文件内容 |
| `write_file` | 写入完整文件（覆盖） |
| `patch` | 精确替换文件中的一段文字 |
| `terminal` | 执行 Shell 命令（subprocess） |
| `search_files` | glob 文件搜索 / 正则内容搜索 |

所有工具都返回字符串（成功时）或 `[错误]` 前缀（失败时）。

### 3.5 CodeAgent

文件路径: `src/lustre/agents/code_agent.py`

```python
class CodeAgent(SpecialistAgent):
    def __init__(self, config: AgentConfig, bus: MessageBus):
        # 从 config 创建 ModelClient
        self._client = create_client(config.model_provider, config.api_key)
        # 创建 ReAct executor
        self._executor = ReActExecutor(
            client=self._client,
            system_prompt=_DEFAULT_CODE_AGENT_PROMPT,
            tools=get_builtin_tools(),
        )

    def process_task(self, task: TaskRequest) -> TaskResult:
        answer, trace = self._executor.execute(
            task=f"# 任务描述\n{task.description}\n\n# 上下文\n{task.context}"
        )
        return TaskResult(task_id=task.task_id, status="completed", output=answer)
```

**System Prompt**（内置默认）：
```python
你是一个专业的 Python 编程助手。

工作方式（ReAct 循环）：
1. 理解任务
2. 规划步骤
3. 行动（使用工具）
4. 观察结果
5. 迭代直到完成

工具：read_file / write_file / patch / terminal / search_files

原则：
- 先了解项目结构再动手
- 写完代码后运行测试验证
- 保持代码简洁、符合 PEP 8
```

### 3.6 CLI 更新

文件路径: `src/lustre/cli.py`

两种运行模式：

| 模式 | 触发条件 | Agent 类型 |
|------|---------|-----------|
| Echo | 无 `ANTHROPIC_API_KEY` | `EchoAgent`（Phase 3 演示用） |
| LLM | 有 `ANTHROPIC_API_KEY` | `CodeAgent`（真正 LLM） |

```python
api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if api_key:
    # Real LLM CodeAgent
    code_agent = CodeAgent(config=agent_cfg, bus=bus)
else:
    # Fallback EchoAgent
    code_agent = CodeEchoAgent(bus=bus)
```

新增命令：
- `/llm` — 切换到 LLM 模式（重载配置）
- `/demo` — 运行 Echo 演示（无需 API key）

---

## 4. 目录结构

```
src/lustre/
├── models/
│   ├── __init__.py
│   ├── client.py       # ModelClient 抽象 + Anthropic/OpenAI 实现
│   └── executor.py     # ReAct 执行器
├── config/
│   ├── __init__.py
│   └── loader.py       # YAML 配置加载 + env var 替换
├── tools/builtin/
│   ├── __init__.py
│   └── tools.py        # 内置工具（read_file / write_file / patch / terminal / search_files）
├── agents/
│   ├── __init__.py     # SpecialistAgent / AgentConfig
│   ├── base.py         # SpecialistAgent 抽象基类
│   ├── code_agent.py   # CodeAgent (LLM-powered) ← Phase 4 新增
│   └── echo_agent.py   # EchoAgent (mock, Phase 2-3)
├── supervisor/
│   ├── state_machine.py
│   ├── planner.py
│   └── supervisor.py
└── cli.py              # v0.4.0，支持两种模式
```

---

## 5. 关键设计决策

### 5.1 为什么用 ReAct 循环？

ReAct（Reason + Act + Observe）是 LLM Agent 的标准范式。它的核心洞察是：**LLM 不是一次性生成完整解决方案，而是通过"行动 → 观察 → 推理"的循环逐步完成任务**。

对于代码生成，这意味着：
- LLM 可以先看项目结构（read_file）
- 再写代码（write_file）
- 再验证（terminal 运行测试）
- 根据验证结果修改（patch）
- 直到测试通过

### 5.2 为什么工具放在 Phase 4 而不是 Phase 6？

按照原计划，工具系统是 Phase 6 的内容。但没有工具的 CodeAgent 只能返回文字，无法实际写文件。为了让 Phase 4 有实际价值（而不是空壳），把内置工具提前到 Phase 4 实现。

### 5.3 为什么配置加载用单例模式？

`load_config()` 返回全局单例。理由：
- 配置在程序生命周期内不变
- 避免每次创建 Agent 都重新解析 YAML
- `reload_config()` 用于测试场景

### 5.4 Anthropic SDK 工具调用格式

Anthropic Claude 的 SDK 响应中，`tool_use` 块的 `input` 字段是 **dict**（不是 JSON 字符串），这与 OpenAI 的 `function.arguments`（字符串）不同。`ReActExecutor` 的 `tool_calls` 统一为 `arguments: dict`，由各 client 负责转换。

---

## 6. 遇到的问题与解决

### 6.1 `@cached_property` + `__slots__` 不兼容

**问题：** `Config` 类同时使用 `__slots__` 和 `@cached_property`，运行时报 `TypeError: No '__dict__' attribute on 'Config' instance'`。

**原因：** `cached_property` 依赖实例 `__dict__` 来缓存值，而 `__slots__` 禁止 `__dict__` 的存在。

**解决：** 去掉 `__slots__`，改用显式惰性属性：
```python
@property
def system(self) -> dict:
    if self._system is None:
        self._system = self._raw.get("system", {})
    return self._system
```

### 6.2 配置文件不在预期位置

**问题：** `configs/config.yaml` 不存在（只有 `configs/config.example.yaml`）。

**原因：** 开发阶段还没有创建 `config.yaml`。

**解决：** `_find_config()` 回退到 `config.example.yaml`：
```python
for name in ("configs/config.yaml", "configs/config.example.yaml"):
    if Path(name).exists():
        return Path(name)
```

### 6.3 EchoAgent 注册表设计过于复杂

**问题：** 最初想把所有 Agent 放进 `SPECIALIST_AGENTS` 注册表，用 `@_register` 装饰器。但 `CodeAgent` 需要额外的 `config` 参数（model、api_key），而 echo agents 不需要。两种需求无法用同一套工厂模式满足。

**解决：** 放弃通用工厂注册表，CLI 里直接按需创建：
```python
if api_key:
    code_agent = CodeAgent(config=agent_cfg, bus=bus)
else:
    code_agent = CodeEchoAgent(bus=bus)
research_impl = EchoAgent(config=research_cfg, bus=bus)
test_impl = EchoAgent(config=test_cfg, bus=bus)
```
`SPECIALIST_AGENTS` 字典废弃，agents `__init__.py` 只保留基本导出。

---

## 7. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| 配置加载 | `LUSTRE_CONFIG=configs/config.example.yaml uv run python -c "from lustre.config.loader import load_config; print(load_config().version)"` | 0.1.0 |
| 所有导入 | `uv run python -c "from lustre.models.client import *; from lustre.models.executor import *; from lustre.tools.builtin import *; print('OK')"` | OK |
| CLI 启动 | `echo "/exit" \| uv run python -m lustre` | Banner + 就绪 |
| /demo 完整流程 | `echo "/demo\n/exit" \| uv run python -m lustre` | research + code 步骤完成 |
| 52 测试通过 | `uv run pytest tests/unit/ -q` | 52 passed |

---

## 8. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| ModelClient | `src/lustre/models/client.py` | Anthropic + OpenAI 统一接口 |
| ReActExecutor | `src/lustre/models/executor.py` | 推理→行动→观察循环 |
| 内置工具 | `src/lustre/tools/builtin/tools.py` | 5 个工具 |
| CodeAgent | `src/lustre/agents/code_agent.py` | LLM 驱动的代码生成 Agent |
| ConfigLoader | `src/lustre/config/loader.py` | YAML + env var |
| CLI v0.4.0 | `src/lustre/cli.py` | Echo/LLM 双模式 |
| 本文档 | `docs/phase-4-llm-integration.md` | 操作记录 |

---

## 9. 下一步

Phase 4 ✅ 完成 → 进入 **Phase 5：Skill 系统**

Phase 5 将实现：
- `prompts/` 下的 System Prompt 模板化（按语言/框架选择不同 prompt）
- `~/.lustre/skills/` 目录的 Skill 加载器
- Skill = prompt 片段 + 初始化脚本 + 每任务脚本
- `/skills` 命令：列出、安装、加载 Skills
