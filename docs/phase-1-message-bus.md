# Phase 1 — 消息总线（Message Bus）

> 日期: 2026-03-30
> 状态: ✅ 完成
> 目标: 实现进程内消息总线，两个 Agent 能通过总线互相发消息

---

## 1. 背景

消息总线是 Lustre Agent 的**最底层基础设施**。

所有 Agent 之间、Agent 与 Supervisor 之间的通信，都经过总线。没有任何 Agent 直接调用另一个 Agent。

**为什么这样设计？**
- **解耦**：Agent 不需要知道其他 Agent 在哪、怎么启动，只要发消息给总线就行
- **可替换**：开发阶段用 `MemoryMessageBus`（进程内，调试方便），生产可切换 `RedisMessageBus`（分布式，多进程），改一行配置
- **可观测**：所有消息都经过总线，可以加日志、监控、追踪

**参考文档：** `docs/architecture-design.md` 第 0 节"开发前必读"

---

## 2. 目标

1. 定义 `Message` / `TaskRequest` / `TaskResult` 数据类
2. 定义 `MessageBus` 抽象接口（供未来 Redis 等实现）
3. 实现 `MemoryMessageBus`（线程安全，进程内）
4. 实现 pub/sub、request/response、loop detection
5. 17 个单元测试，全部通过

---

## 3. 操作步骤

### 3.1 定义 Message 数据类

文件路径: `src/lustre/bus/message.py`

```python
@dataclass
class Message:
    id: str                           # UUID
    sender: str                       # "supervisor" | "code" | "test" | "research"
    recipient: str | None            # None = 广播
    type: MessageType | str           # 消息类型
    payload: dict                    # 消息体
    conversation_id: str              # 关联的会话 ID
    timestamp: datetime
    hops: int = 0                    # 防死循环计数
    reply_to: str | None             # 回复哪条消息
    metadata: dict = field(default_factory=dict)
```

**关键设计决策：**

- `hops` 字段用于防死循环。消息每次转发 hops+1，超过 `max_hops`（默认 10）则丢弃
- `reply_to` 用于 request/response 模式，回复消息引用原消息 ID
- `conversation_id` 将多条消息关联到同一个任务会话

### 3.2 定义 MessageType 枚举

```python
class MessageType(str, Enum):
    # Supervisor → Specialist
    TASK_REQUEST = "task_request"
    ABORT = "abort"
    RETRY = "retry"

    # Specialist → Supervisor
    TASK_RESULT = "task_result"
    HEARTBEAT = "heartbeat"
    ERROR = "error"

    # System
    HUMAN_CONFIRMATION = "human_confirmation"
    SYSTEM_SHUTDOWN = "system_shutdown"
```

### 3.3 定义 TaskRequest 和 TaskResult

```python
@dataclass
class TaskRequest:
    task_id: str
    description: str
    context: dict[str, Any] = field(default_factory=dict)
    skills_requested: list[str] = field(default_factory=list)
    confirmation_needed: bool = False
    confirmation_prompt: str | None = None
    priority: int = 0

@dataclass
class TaskResult:
    task_id: str
    status: str  # "completed" | "failed" | "partial"
    output: str = ""
    error: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)  # path → content
    agent_name: str = ""
```

### 3.4 定义 MessageBus 抽象接口

文件路径: `src/lustre/bus/base.py`

```python
class MessageBus(ABC):
    @abstractmethod
    def publish(self, topic: str, message: Message) -> None: ...

    @abstractmethod
    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> Subscription: ...

    @abstractmethod
    def unsubscribe(self, subscription: Subscription) -> None: ...

    @abstractmethod
    def request(self, topic: str, message: Message, timeout: float = 30.0) -> Message: ...

    @abstractmethod
    def list_topics(self) -> list[str]: ...
```

**Topic 命名约定：**
```
task.<agent_name>        — Supervisor 分发任务给某 Agent
result.<agent_name>      — Agent 返回结果给 Supervisor
*                        — 广播（所有订阅者都收到）
```

### 3.5 实现 MemoryMessageBus

文件路径: `src/lustre/bus/memory_bus.py`

```python
class MemoryMessageBus(MessageBus):
    def __init__(self, max_hops: int = 10) -> None:
        self._max_hops = max_hops
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[_SubscriptionRecord]] = defaultdict(list)
        self._pending_replies: dict[str, threading.Event] = {}
```

**核心机制：**

- `threading.RLock()` 保护所有状态，线程安全
- `_subscribers` 是 `topic → [callback, callback, ...]` 的字典
- 回调函数在锁内执行，保持快且简单，避免死锁
- `request()` 用 `threading.Event` 实现同步等待，替代复杂的 Future

**publish 流程：**
```
publish(topic, message)
  → 检查 hops >= max_hops？丢弃 → return
  → 加锁 → 取出所有 subscriber
  → 对每个 callback 调用 callback(message)
    → 如有异常记录日志，不影响其他 callback
```

**request 流程（同步请求/响应）：**
```
request(topic, message, timeout)
  → 创建 threading.Event
  → 临时订阅 result.<sender>
  → publish(topic, message)
  → event.wait(timeout)
  → 收到回复 → return reply
  → 超时 → TimeoutError
  → finally: 退订，清理 Event
```

### 3.6 更新 bus/__init__.py

```python
from lustre.bus.base import MessageBus, Subscription
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType, TaskRequest, TaskResult

__all__ = [
    "Message", "MessageType", "TaskRequest", "TaskResult",
    "MessageBus", "MemoryMessageBus", "Subscription",
]
```

### 3.7 写单元测试

文件路径: `tests/unit/bus/test_memory_bus.py`

覆盖场景：

| 测试 | 验证什么 |
|------|---------|
| `test_publish_delivers_to_subscriber` | 发送 → 正确 subscriber 收到 |
| `test_publish_to_multiple_subscribers` | 同一 topic 多个 subscriber 都收到 |
| `test_publish_to_wrong_topic` | 发到错误 topic 不收到 |
| `test_broadcast_wildcard` | `*` 通配符订阅收到所有消息 |
| `test_unsubscribe_stops_delivery` | 取消订阅后不再收到 |
| `test_list_topics` | 能列出当前有订阅者的 topic |
| `test_message_increment_hops` | hops 递增，原消息不变 |
| `test_message_to_dict_roundtrip` | 序列化/反序列化完整 |
| `test_message_from_dict_with_string_type` | 字符串 type 能还原为枚举 |
| `test_task_request_to_dict` | TaskRequest 序列化正确 |
| `test_task_result_to_dict` | TaskResult 序列化正确 |
| `test_max_hops_discard` | hops 达到上限的消息被丢弃 |
| `test_increment_hops_near_limit` | 接近上限的消息下一跳被丢弃 |
| `test_concurrent_publish` | 4 线程并发发布 400 条，无丢失 |
| `test_callback_exception_does_not_crash_bus` | 回调异常不影响总线和其他回调 |
| `test_request_response_success` | request/response 正常返回 |
| `test_request_timeout` | 超时抛出 TimeoutError |

**并发测试说明：**
```python
def test_concurrent_publish(bus):
    def _publish():
        for _ in range(100):
            bus.publish("task.code", Message(...))
    threads = [threading.Thread(target=_publish) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(received) == 400
```

### 3.8 安装 dev 依赖并运行测试

```bash
cd /Users/eva/code/Lustre-Agent

# dev 依赖在 optional-dependencies 里，用 --extra 安装
uv sync --extra dev

# 运行测试
uv run pytest tests/unit/bus/test_memory_bus.py -v
```

**测试输出：**
```
tests/unit/bus/test_memory_bus.py::test_publish_delivers_to_subscriber PASSED [  5%]
tests/unit/bus/test_memory_bus.py::test_publish_to_multiple_subscribers PASSED [ 11%]
...
tests/unit/bus/test_memory_bus.py::test_request_timeout PASSED [100%]

============================== 17 passed in 0.53s ==============================
```

---

## 4. 目录结构

```
src/lustre/
├── bus/
│   ├── __init__.py          # 导出主要类型
│   ├── base.py              # MessageBus 抽象接口
│   ├── memory_bus.py        # MemoryMessageBus 实现（Phase 1 交付物）
│   └── message.py           # Message / TaskRequest / TaskResult 数据类
│                               （Phase 1 交付物）
│
tests/
└── unit/
    └── bus/
        └── test_memory_bus.py  # 17 个单元测试（Phase 1 交付物）
```

---

## 5. 关键设计决策

### 5.1 为什么用 `threading.RLock()` 而不是 `threading.Lock()`？

`RLock` 允许同一线程多次获取锁。在 `request()` 里可能出现在已持锁的情况下需要再次操作共享数据的场景，`RLock` 更安全。

### 5.2 为什么回调在锁内执行？

简化并发模型。如果允许回调在锁外执行，subscriber 列表可能在回调执行期间被另一个线程修改（unsubscribe），导致不一致。

但这也意味着**回调函数不能有阻塞操作**。对于需要长时间运行的回调，应该用 `ThreadPoolExecutor` 异步分发，但这属于优化，不是 Phase 1 的范围。

### 5.3 为什么用 `threading.Event` 而不是 `concurrent.futures.Future`？

`Event` 更轻量，语义正好对应"等待一个信号"。`Future` 适合需要链式处理、取消、回调注册等场景，这里不需要那么重的机制。

### 5.4 `max_hops` 默认 10 是怎么来的？

参考网络路由的 TTL 设计。Agent 协作路径不会太长，10 跳已经能覆盖大多数场景。如果真的需要更大的跳数，可以配置。

---

## 6. 遇到的问题与解决

### 6.1 uv sync 找不到 `dev` group

**问题：**
```
error: Group `dev` is not defined in the project's `dependency-groups` table
```

**原因：** dev 依赖写在 `[project.optional-dependencies]` 而不是 `[dependency-groups]`。

**解决：** 用 `uv sync --extra dev` 安装 optional dev 依赖。

**说明：** 这是 uv 对 dependency-groups 和 optional-dependencies 的区分。前者是 PEP 735 标准的 dependency groups，后者是传统 optional 依赖。pyproject.toml 里应该用 `uv sync --extra dev` 来安装。

### 6.2 pytest 在项目根目录找不到命令

**问题：**
```
error: Failed to spawn: `pytest`
  Caused by: No such file or directory (os error 2)
```

**原因：** pytest 没安装进虚拟环境（因为还没装 dev 依赖）。

**解决：** 先 `uv sync --extra dev`，再 `uv run pytest ...`。

---

## 7. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| dev 依赖安装 | `uv sync --extra dev` | 无 error，ruff mypy pytest installed |
| 所有测试通过 | `uv run pytest tests/unit/bus/test_memory_bus.py -v` | 17 passed |
| 模块可 import | `uv run python -c "from lustre.bus import Message, MemoryMessageBus"` | 无 error |
| request 超时正确 | `uv run pytest tests/unit/bus/test_memory_bus.py::test_request_timeout -v` | PASSED |
| 并发安全 | `uv run pytest tests/unit/bus/test_memory_bus.py::test_concurrent_publish -v` | PASSED |

---

## 8. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| Message 数据类 | `src/lustre/bus/message.py` | Message、TaskRequest、TaskResult、MessageType |
| MessageBus 接口 | `src/lustre/bus/base.py` | 抽象基类 + Subscription |
| MemoryMessageBus | `src/lustre/bus/memory_bus.py` | 线程安全进程内实现 |
| bus 导出 | `src/lustre/bus/__init__.py` | 统一导出 |
| 单元测试 | `tests/unit/bus/test_memory_bus.py` | 17 个测试 |
| 本文档 | `docs/phase-1-message-bus.md` | 操作记录 |

---

## 9. 下一步

Phase 1 ✅ 完成 → 进入 **Phase 2：Agent 基类（不含 LLM）**

Phase 2 将实现：
- `lustre/agents/base.py` — SpecialistAgent 基类，可接收任务、返回结果
- `lustre/agents/echo_agent.py` — 开发阶段用的模拟 Agent（不接 LLM）
- 修改 `cli.py`，连接总线，跑通"发任务→收结果"全流程
