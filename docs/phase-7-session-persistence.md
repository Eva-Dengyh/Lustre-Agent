# Phase 7 — Session 持久化（SQLite）

> 日期: 2026-04-16
> 状态: ✅ 完成
> 目标: SQLite 会话持久化 + /sessions CLI 命令

---

## 1. 背景

Phase 1-6 所有数据都在内存，程序退出后丢失。Phase 7 的目标：
- 用 SQLite 持久化会话历史
- 支持多会话（创建/切换/删除）
- 全局搜索历史消息
- `/sessions` CLI 命令

---

## 2. 目标

1. 实现 `SessionStore`（SQLite 直接封装）
2. 实现 `SessionManager`（会话生命周期管理）
3. 实现 `/sessions` CLI 命令
4. 52 个单元测试全部通过

---

## 3. 操作步骤

### 3.1 SQLite Schema

文件路径: `src/lustre/session/store.py`

```sql
sessions(id, title, created_at, updated_at, metadata)
messages(id, session_id, role, content, tool_call_id, tool_name, created_at)

-- 索引
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- FTS5 全文搜索
CREATE VIRTUAL TABLE messages_fts USING fts5(content, content=messages, ...);
```

### 3.2 数据模型

```python
@dataclass
class Message:
    id: str
    role: str           # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None
    tool_name: str | None
    created_at: str    # ISO 8601

@dataclass
class Session:
    id: str
    title: str
    messages: list[Message]
    metadata: dict
    created_at: str
    updated_at: str
```

### 3.3 SessionStore 核心方法

```python
store = SessionStore()  # 默认 ~/.lustre/sessions.db

session = store.create_session(title="调研 FastAPI")
msg = store.add_message(session.id, "user", "帮我调研...")
history = store.get_recent_messages(session.id, limit=50)
results = store.search_messages("FastAPI 性能")  # FTS5 搜索
```

**线程安全：** `threading.RLock()` 保护所有写操作。

### 3.4 SessionManager

```python
sm = SessionManager()
sm.create_session("新项目")
sm.log_message("user", "帮我写 FastAPI")
sm.log_message("assistant", "好的...")

# 获取历史给 LLM
history = sm.get_history()  # [{"role": "user", "content": "..."}]

# 切换会话
sm.switch_session("session-id")
```

### 3.5 /sessions CLI 命令

```
/sessions                  — 列出所有会话
/sessions new <标题>       — 创建新会话
/sessions switch <id>      — 切换到指定会话
/sessions delete <id>      — 删除会话
/sessions rename <id> <标题> — 重命名会话
/sessions search <关键词>   — 全文搜索
```

---

## 4. 关键设计决策

### 4.1 为什么直接用 sqlite3 而不是 aiosqlite？

项目还没引入 asyncio。直接用 `sqlite3`（同步）+ `threading.RLock()` 实现线程安全，避免异步复杂性。等到真正需要高并发时再切换。

### 4.2 WAL 模式

```python
conn.execute("PRAGMA journal_mode=WAL")
```

WAL（Write-Ahead Logging）让读写可以并发进行，提升并发性能。

### 4.3 FTS5 全文搜索

```python
CREATE VIRTUAL TABLE messages_fts USING fts5(content, ...)
```

SQLite 内置的 FTS5 插件支持高效全文搜索，无需额外的搜索引擎。

### 4.4 Session 和 Message 分离

Session 和 Message 是两个表，通过 `session_id` 外键关联。
而不是把 messages 直接序列化存在 session.metadata 里。
这样支持消息级别的搜索和统计。

---

## 5. 遇到的问题与解决

### 5.1 循环导入：session.__init__ 导入 manager

**问题：** `__init__.py` 导入 `SessionManager`，但 `manager.py` 可能还不存在。

**解决：** `manager.py` 是和 `__init__.py` 同时创建的，不存在循环导入问题。测试时用 `tempfile.TemporaryDirectory()` 确保隔离。

---

## 6. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| CLI /sessions | `echo "/sessions\n/exit" \| uv run python -m lustre` | 表格显示会话列表 |
| /sessions new | `echo "/sessions new 测试会话\n/exit" \| uv run python -m lustre` | 创建成功 |
| 52 测试通过 | `uv run pytest tests/unit/ -q` | 52 passed |

---

## 7. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| SessionStore | `src/lustre/session/store.py` | SQLite 封装（FTS5/WAL/线程安全） |
| SessionManager | `src/lustre/session/manager.py` | 会话生命周期管理 |
| Session 模块 | `src/lustre/session/__init__.py` | 导出 Session/ SessionStore/ SessionManager |
| CLI 更新 | `src/lustre/cli.py` | /sessions 命令 |
| 本文档 | `docs/phase-7-session-persistence.md` | 操作记录 |

---

## 8. 下一步

Phase 7 ✅ 完成 → 进入 **Phase 8：CLI 完善**

Phase 8 将实现：
- Rich 交互界面（彩色输出、面板、分页）
- 进度条（Agent 执行中显示动画）
- `~/.lustre/` 配置文件管理（`/config` 命令）
- `lustre_cli/` 子命令（`lustre init` / `lustre skills install`）
