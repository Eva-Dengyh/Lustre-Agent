# Phase 6 — 内置工具（完整版）

> 日期: 2026-04-16
> 状态: ✅ 完成
> 目标: 工具注册表 + 访问控制 + CLI /tools 命令

---

## 1. 背景

Phase 4/5 内置工具直接以 `ToolDef` 实例列表传给 `ReActExecutor`，没有统一的注册机制。Phase 6 的目标：

1. 建立中央 `ToolRegistry`，所有工具通过 `@register_tool` 装饰器注册
2. 实现 `AgentToolPolicy`，控制哪些 Agent 用哪些工具
3. `builtin/tools.py` 改造为自注册模块（import 时自动注册）
4. 实现 `/tools` CLI 命令

---

## 2. 操作步骤

### 2.1 ToolRegistry

文件路径: `src/lustre/tools/registry.py`

```python
registry = get_tool_registry()
registry.register(ToolDef(name="...", ...))
registry.is_registered("read_file")  # True

# 装饰器方式
@register_tool(name="my_tool", description="...", parameters={...})
def my_tool(args, task_id): return "ok"
```

**核心功能：**
- `register(tool_def)` — 注册工具
- `get(name)` / `all_tools()` / `enabled_tools()` — 查询
- `enable_tool(name)` / `disable_tool(name)` — 全局开关
- `get_tools(names=, owner=)` — 按名称或所有者过滤
- `get_schemas()` — 导出 LLM 需要的 JSON Schema

### 2.2 消除 ToolDef 重复定义

**问题：** `executor.py` 和 `registry.py` 各有一个 `ToolDef`。

**解决：** 统一在 `registry.py`，`executor.py` 从其导入。

同时把 `tool_def.function(args)` 改为 `tool_def.invoke(args)`，让 ToolDef 本身封装调用逻辑。

### 2.3 builtin/tools.py 改造

**改造前：**
```python
def get_builtin_tools() -> list[ToolDef]:
    return [
        ToolDef(name="read_file", ..., function=tool_read_file),
        ...
    ]
```

**改造后：**
```python
# 装饰器在 import 时自动注册
@register_tool(name="read_file", description="...", parameters={...})
def _tool_read_file(args, task_id): ...

def get_builtin_tools() -> list[ToolDef]:
    return get_tool_registry().get_tools(owner="builtin")
```

模块级别装饰器 → import 触发注册。

### 2.4 AgentToolPolicy

文件路径: `src/lustre/tools/access.py`

**默认策略：**
| Agent | 允许的工具 |
|-------|---------|
| code | 所有工具 |
| research | read_file, search_files（只读） |
| test | read_file, search_files, terminal（可运行测试） |

```python
policy = AgentToolPolicy()
code_tools = policy.get_tools_for_agent("code")
# research_tools = policy.get_tools_for_agent("research")
# → ["read_file", "search_files"]

# 支持运行时 override
tools = policy.get_tools_for_agent("research", denylist=["read_file"])
```

### 2.5 /tools CLI 命令

```
/tools              — 显示所有已注册工具
/tools enable <n>  — 启用工具
/tools disable <n> — 禁用工具
/tools policy <agent> — 查看某 Agent 的工具策略
```

---

## 3. 关键设计决策

### 3.1 为什么用装饰器而不是显式注册？

装饰器让工具定义和注册在同一个地方，降低遗忘注册的概率。
自注册模式：`import lustre.tools.builtin` → 所有装饰器执行 → 工具进入 registry。

### 3.2 ToolDef.invoke() vs function 属性？

ToolDef 现在封装了调用逻辑（`invoke()` 方法），而不是把 `function` 暴露为公有属性。
未来可以在 `invoke()` 里加拦截逻辑（日志、访问控制、超时）。

### 3.3 AgentToolPolicy 为什么用 None 表示"全部允许"？

```python
DEFAULT_POLICY = {
    "code": None,        # 所有工具
    "research": ["read", "search"],  # 白名单
}
```

`None` 表示"无限制"，比空列表更语义清晰。
`get_tools()` 里对 `None` 做特判：`tool_names is None → return all enabled`。

---

## 4. 遇到的问题与解决

### 4.1 循环导入

**问题：** `executor.py` 需要 `ToolDef`，`registry.py` 定义了 `ToolDef`。

**解决：** 两个文件都在 `src/lustre/` 下，Python 按需解析 import，不产生循环（`executor.py` 导入 `registry`，`registry` 不导入 executor）。

### 4.2 builtin 模块未导入导致注册失败

**问题：** 如果 `tools/__init__.py` 只导入 `registry` 不导入 `builtin`，工具不会被注册。

**解决：** `tools/__init__.py` 显式 `from lustre.tools import builtin` 触发自注册。

---

## 5. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| 5 工具注册 | `uv run python -c "from lustre.tools import get_tool_registry; print(get_tool_registry().names())"` | `['patch', 'read_file', 'search_files', 'terminal', 'write_file']` |
| owner=builtin | `uv run python -c "from lustre.tools import get_all_tools; print([t.name for t in get_all_tools()])"` | 5 个工具 |
| access policy | `uv run python -c "from lustre.tools.access import AgentToolPolicy; p=AgentToolPolicy(); print([t.name for t in p.get_tools_for_agent('research')])"` | `['read_file', 'search_files']` |
| 52 测试通过 | `uv run pytest tests/unit/ -q` | 52 passed |

---

## 6. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| 注册表 | `src/lustre/tools/registry.py` | ToolRegistry + @register_tool |
| 访问控制 | `src/lustre/tools/access.py` | AgentToolPolicy |
| 工具模块 | `src/lustre/tools/__init__.py` | 导出 + builtin 导入 |
| 内置工具 | `src/lustre/tools/builtin/tools.py` | 5 个工具（自注册） |
| 本文档 | `docs/phase-6-builtin-tools.md` | 操作记录 |

---

## 7. 下一步

Phase 6 ✅ 完成 → 进入 **Phase 7：Session 持久化（SQLite）**

Phase 7 将实现：
- `lustre/session/` 模块（SQLite 会话存储）
- `SessionStore` 类（保存/恢复对话历史）
- `SessionManager`（多会话管理）
- `lustre_cli/session.py`（`/sessions` 命令）
