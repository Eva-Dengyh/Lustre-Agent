# Phase 9 — Redis 消息总线

> 日期: 2026-04-16
> 状态: ✅ 完成
> 目标: Redis Streams 分布式消息总线 + 一键切换

---

## 1. 背景

Phase 1 实现了内存消息总线（`MemoryMessageBus`），进程内通信，调试方便。
Phase 9 的目标：实现 `RedisMessageBus`，支持跨进程、跨机器通信，只需改一行配置。

**架构原则（来自 architecture-design.md）：**

> 消息总线是最底层依赖。所有 Agent 之间、Agent 与 Supervisor 之间的通信，都经过消息总线。
>
> - 当前：MemoryMessageBus（进程内，调试方便）
> - 未来：RedisMessageBus（分布式，多进程）
> - 切换方式：改一行配置

---

## 2. 技术方案

### 2.1 为什么用 Redis Streams 而不是 Pub/Sub？

| 特性 | Pub/Sub | Streams |
|------|---------|---------|
| 持久性 | 无（消息发出即消失） | 有（AOF/RDB 持久化） |
| 消息回溯 | 不支持 | 支持（可 XREAD 从任意位置读取） |
| 消费者组 | 不支持 | 支持（XREADGROUP，负载均衡） |
| 消息确认 | 不支持 | 支持（XACK） |

Lustre Agent 需要：
- **请求/响应模式**（Supervisor 发任务 → Agent 回结果）：Streams + XREADGROUP
- **消息持久性**（Agent 重启后能继续消费）：Streams
- **消费者组**（多进程读取同一 topic 负载均衡）：XREADGROUP

### 2.2 Stream Key 命名

```
lustre:stream:<topic>    — 消息流，如 lustre:stream:task.code
lustre:reply:<msg_id>   — 请求/响应的临时回复流
```

### 2.3 RedisMessageBus 实现要点

**publish：**
```python
self._redis.xadd(
    stream_key,
    {"data": json.dumps(message.to_dict())},
    maxlen=100_000,  # 防止无限增长
    approximate=True,
)
```

**subscribe（XREADGROUP）：**
```python
messages = conn.xreadgroup(
    groupname="lustre-subscribers",
    consumername=self._consumer_name,
    streams={stream_key: "$"},  # "$" = only new messages
    count=10,
    block=5000,  # 5s blocking
)
```

**request/response：**
```python
# 订阅临时 reply stream
reply_sub = self.subscribe(f"lustre:reply:{msg_id}", callback)
# 发请求到 topic stream
self.publish("task.code", message)
# 等待回复
reply = reply_received.wait(timeout=30.0)
```

---

## 3. 接口统一

### 3.1 工厂函数

```python
from lustre.bus import create_message_bus

# 内存总线（开发）
bus = create_message_bus("memory")

# Redis 总线（生产）
bus = create_message_bus("redis", url="redis://localhost:6379/0")
```

### 3.2 Config.create_bus()

```python
cfg = load_config()
bus = cfg.create_bus()  # 读 config.yaml 的 message_bus.type
```

**config.yaml：**
```yaml
message_bus:
  type: redis
  url: redis://localhost:6379/0
```

### 3.3 接口完全一致

```python
bus.publish("task.code", message)     # ✅ MemoryMessageBus
bus.publish("task.code", message)     # ✅ RedisMessageBus

bus.subscribe("result.code", callback)  # ✅ 两者都有
bus.request("task.code", message)      # ✅ 两者都有
```

---

## 4. 关键设计决策

### 4.1 惰性连接

```python
@property
def _redis(self) -> redis.Redis:
    if self._pool is None:
        self._pool = redis.ConnectionPool.from_url(self._url)
    return redis.Redis(connection_pool=self._pool)
```

连接在第一次使用时才建立，而不是 `__init__`。这样即使 Redis 没运行，程序也能启动（只是发消息会失败）。

### 4.2 优雅降级

```python
try:
    from lustre.bus.redis_bus import RedisMessageBus
except Exception:
    RedisMessageBus = None
```

如果 `redis` 包没安装，导入不会失败，只是 `RedisMessageBus = None`。用户会收到清晰的错误信息。

### 4.3 消费者组（Consumer Group）

```python
self._redis.xgroup_create(stream_key, "lustre-subscribers", id="0", mkstream=True)
```

`mkstream=True`：如果 Stream 不存在则自动创建。每个 Topic 一个 Stream，多个进程共享同一个消费者组，实现**负载均衡**——一条消息只被一个消费者处理。

---

## 5. 使用示例

### 开发（本地，无需 Redis）
```yaml
# config.yaml
message_bus:
  type: memory
```
```python
bus = create_message_bus("memory")
agent = SpecialistAgent(bus=bus)
```

### 生产（多进程）
```yaml
# config.yaml
message_bus:
  type: redis
  url: redis://redis-server:6379/0
```
```python
# Supervisor 进程
cfg = load_config()
bus = cfg.create_bus()
sup = Supervisor(bus=bus, agents={...})

# Agent 进程（可以分布在不同机器）
bus = cfg.create_bus()
agent = SpecialistAgent(bus=bus)
agent.start()
```

---

## 6. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| 导入 | `uv run python -c "from lustre.bus import RedisMessageBus; print('OK')"` | OK |
| 工厂 memory | `uv run python -c "from lustre.bus import create_message_bus; b=create_message_bus('memory'); print(type(b).__name__)"` | MemoryMessageBus |
| 工厂 redis | `uv run python -c "from lustre.bus import create_message_bus; b=create_message_bus('redis', url='redis://localhost:6379/15'); print(type(b).__name__)"` | RedisMessageBus |
| 接口方法 | `uv run python -c "from lustre.bus import RedisMessageBus; print([m for m in dir(RedisMessageBus()) if not m.startswith('_')])"` | 7 个方法 |
| 52 测试 | `uv run pytest tests/unit/ -q` | 52 passed |

---

## 7. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| RedisMessageBus | `src/lustre/bus/redis_bus.py` | Redis Streams 实现 |
| 总线导出 | `src/lustre/bus/__init__.py` | 导出 + `create_message_bus()` |
| Config 更新 | `src/lustre/config/loader.py` | `Config.create_bus()` |
| 本文档 | `docs/phase-9-redis-bus.md` | 操作记录 |

---

## 8. 下一步

Phase 9 ✅ 完成 → **项目全部完成**

Lustre Agent Phase 0-9 全部完成：

| Phase | 内容 | 状态 |
|-------|------|------|
| 0 | 项目骨架 | ✅ |
| 1 | 消息总线 | ✅ |
| 2 | Agent 基类 | ✅ |
| 3 | Supervisor 状态机 | ✅ |
| 4 | LLM 集成 | ✅ |
| 5 | Skill 系统 | ✅ |
| 6 | 内置工具 | ✅ |
| 7 | Session 持久化 | ✅ |
| 8 | CLI 完善 | ✅ |
| 9 | Redis 消息总线 | ✅ |

**下一步建议（可选）：**
- **Phase 10**： MCP 集成（Model Context Protocol，支持的工具扩展到浏览器/文件系统/代码执行等）
- **Phase 11**： Web UI（Gradio/Streamlit，可视化任务看板）
- **Phase 12**： 部署脚本（Docker / Nix / Homebrew）
