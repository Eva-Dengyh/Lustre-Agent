# Phase 2 — Agent 基类（不含 LLM）

> 日期: 2026-03-30
> 状态: ✅ 完成
> 目标: 实现 SpecialistAgent 基类和模拟 Agent，能通过消息总线收发任务

---

## 1. 背景

Phase 1 建立了消息总线，Agent 之间能通过总线发消息。
Phase 2 的目标是：**让 Agent 能订阅任务主题、处理任务、返回结果**。

此时 Agent 还不接 LLM（Phase 4 才接），所以用 `EchoAgent` 做模拟：
收到什么任务就 echo 回什么描述，用于验证整个流程正确。

**参考文档：** `docs/architecture-design.md` 第 0 节

---

## 2. 目标

1. 实现 `SpecialistAgent` 抽象基类（订阅 → 处理 → 回复）
2. 实现 `EchoAgent` 模拟 Agent
3. 修改 `cli.py`，接入总线和 Agent，新增 `/demo` 命令
4. 演示"发任务 → 总线 → EchoAgent → 总线 → 收到结果"全流程
5. 10 个单元测试，全部通过

---

## 3. 操作步骤

### 3.1 AgentConfig 数据类

文件路径: `src/lustre/agents/base.py`

```python
@dataclass
class AgentConfig:
    name: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    api_key: str | None = None
```

**说明：** 每个 Agent 的配置。Phase 4 接 LLM 时，`model_provider`、`model_name`、`api_key` 会被用到。

### 3.2 SpecialistAgent 抽象基类

```python
class SpecialistAgent(ABC):
    def __init__(self, config: AgentConfig, bus: MessageBus) -> None:
        self.config = config
        self.bus = bus
        self._running = False
        self._subscription = None

    def start(self) -> None:
        topic = f"task.{self.name}"
        self._subscription = self.bus.subscribe(topic, self._on_message)

    def stop(self) -> None:
        if self._subscription is not None:
            self.bus.unsubscribe(self._subscription)

    def _on_message(self, message: Message) -> None:
        # 解析任务 → 调用 process_task → 发布结果
        task_request = self._parse_task_request(message)
        result = self.process_task(task_request)
        self._publish_result(message, result)

    @abstractmethod
    def process_task(self, task: TaskRequest) -> TaskResult:
        """子类实现具体任务逻辑"""
        ...
```

**生命周期：**
```
create() → start() → [handles tasks] → stop()
```

**Topic 约定：**
- 监听：`task.<name>`（如 `task.code`）
- 回复：`result.<name>`（如 `result.code`）

**错误处理：** `_on_message` 用 try/except 包裹所有逻辑，确保一个 Agent 的崩溃不影响总线和其他 Agent。

### 3.3 EchoAgent 模拟 Agent

文件路径: `src/lustre/agents/echo_agent.py`

```python
class EchoAgent(SpecialistAgent):
    def process_task(self, task: TaskRequest) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            status="completed",
            output=f"[EchoAgent] Received: {task.description}",
            agent_name=self.name,
        )
```

**用途：**
- 开发阶段验证总线流程，不需要真实 LLM API Key
- Phase 4 会被 `CodeAgent`、`TestAgent`、`ResearchAgent` 替换

### 3.4 Agent 注册表

文件路径: `src/lustre/agents/__init__.py`

```python
SPECIALIST_AGENTS: dict[str, type[SpecialistAgent]] = {
    "code": CodeEchoAgent,
    "test": CodeEchoAgent,
    "research": CodeEchoAgent,
}
```

**说明：** 用字典做注册表，CLI 和未来的 Supervisor 可以通过名字查到对应的 Agent 类，做动态实例化。

### 3.5 更新 CLI（接入总线）

文件路径: `src/lustre/cli.py`

新增内容：
- 全局 `_bus: MemoryMessageBus` 共享实例
- `/demo` 命令：演示完整流程

```python
def run_demo() -> None:
    bus = MemoryMessageBus()
    agent = CodeEchoAgent(bus=bus)
    agent.start()

    # Supervisor 发送任务
    bus.publish("task.code", Message(
        sender="supervisor",
        type=MessageType.TASK_REQUEST,
        payload=task_request.to_dict(),
        conversation_id=conversation_id,
    ))

    # 等待结果
    bus.subscribe("result.code", results.append)
    # ...
```

### 3.6 运行演示

```bash
cd /Users/eva/code/Lustre-Agent

echo "/demo
/exit" | uv run python -m lustre
```

**输出：**
```
=== 总线演示 (Phase 2) ===
+ CodeEchoAgent 已启动 (listening on task.code)
→ Supervisor 发送任务到总线:
       task_id=task-419025
       description=Write a hello world FastAPI endpoint
→ 等待 CodeEchoAgent 响应...
✓ CodeEchoAgent 响应:
       sender=code
       status=completed
       output=[EchoAgent] Received: Write a hello world FastAPI endpoint
       reply_to=<original-message-id>
```

### 3.7 写单元测试

文件路径: `tests/unit/agents/test_base.py`

覆盖场景：

| 测试 | 验证什么 |
|------|---------|
| `test_agent_start_stop` | start/stop 状态正确 |
| `test_agent_double_start_no_crash` | 重复 start 不崩溃 |
| `test_agent_stop_when_not_started` | 未 start 就 stop 不崩溃 |
| `test_agent_receives_task_and_replies` | 发任务 → 收结果 |
| `test_agent_ignores_messages_when_stopped` | stop 后不收消息 |
| `test_agent_reply_has_reply_to_set` | 回复包含 reply_to |
| `test_echo_agent_returns_completed` | EchoAgent 返回 completed |
| `test_code_echo_agent_name_is_code` | CodeEchoAgent 名字是 code |
| `test_agent_config_defaults` | AgentConfig 默认值正确 |
| `test_agent_catches_process_exception` | process_task 异常不影响总线 |

```bash
uv run pytest tests/unit/agents/test_base.py -v
```

**输出：**
```
============================== 10 passed in 0.22s ==============================
```

---

## 4. 目录结构

```
src/lustre/
├── agents/
│   ├── __init__.py          # AgentConfig, EchoAgent, SPECIALIST_AGENTS
│   ├── base.py              # SpecialistAgent 抽象基类（Phase 2 交付物）
│   └── echo_agent.py        # EchoAgent / CodeEchoAgent（Phase 2 交付物）
│
tests/
└── unit/
    └── agents/
        └── test_base.py     # 10 个单元测试（Phase 2 交付物）
```

---

## 5. 关键设计决策

### 5.1 Agent 不直接调用其他 Agent

SpecialistAgent 只订阅总线、响应任务，不持有其他 Agent 的引用。
这是 Phase 1 就定下的原则：**总线是唯一通信通道**。

### 5.2 错误不向上传播

`_on_message` 捕获所有异常，返回 `TaskResult(status="failed", error=...)`。
这样 Supervisor 总能收到一个回复，即使 Agent 内部出错。

### 5.3 `process_task` 是抽象方法

子类必须实现，这正是 Phase 4 接 LLM 时要改的地方：
```python
def process_task(self, task: TaskRequest) -> TaskResult:
    # Phase 4: call LLM here
    response = self.llm.complete(...)
    return TaskResult(...)
```

### 5.4 为什么用 `time.sleep` 而非 `threading.Event` 等待测试结果？

测试代码中：
```python
for _ in range(50):
    if results:
        break
    time.sleep(0.05)
```

这是测试中的轮询，不是生产代码。生产用 `bus.request()`（已在 Phase 1 实现）。

---

## 6. 遇到的问题与解决

### 6.1 EchoAgent 缺少 `MessageBus` 类型导入

**问题：** `echo_agent.py` 使用 `MessageBus` 类型注解，但没 import。

**解决：** `from __future__ import annotations` 延迟注解解析，不需要 import。只在 `bus: MessageBus` 这种注解里用，不影响运行时。

---

## 7. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| CLI 启动 | `echo "/exit" \| uv run python -m lustre` | Banner + "再见！" |
| /demo 完整流程 | `echo "/demo\n/exit" \| uv run python -m lustre` | CodeEchoAgent 收到并回复 |
| reply_to 正确 | 查看 /demo 输出 | reply_to = 原消息 ID |
| Agent 单元测试 | `uv run pytest tests/unit/agents/test_base.py -v` | 10 passed |
| 进程不出错 | `echo "/demo\n/demo\n/exit" \| uv run python -m lustre` | 无 traceback |

---

## 8. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| SpecialistAgent 基类 | `src/lustre/agents/base.py` | 抽象基类，start/stop/message handling |
| EchoAgent | `src/lustre/agents/echo_agent.py` | 模拟 Agent，不接 LLM |
| agents 导出 | `src/lustre/agents/__init__.py` | AgentConfig + SPECIALIST_AGENTS |
| CLI 更新 | `src/lustre/cli.py` | 新增 /demo 命令，v0.2.0 |
| 单元测试 | `tests/unit/agents/test_base.py` | 10 个测试 |
| 本文档 | `docs/phase-2-agent-base.md` | 操作记录 |

---

## 9. 下一步

Phase 2 ✅ 完成 → 进入 **Phase 3：Supervisor 状态机**

Phase 3 将实现：
- `lustre/supervisor/state_machine.py` — Supervisor 状态机（Idle → Planning → AwaitingConfirmation → Executing → Done）
- `lustre/supervisor/planner.py` — 任务拆解（分析用户需求 → 列出步骤 → 列出 Agent 安排）
- 修改 `cli.py`，连接 Supervisor，跑通完整人机协作流程
