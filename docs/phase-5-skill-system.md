# Phase 5 — Skill 系统

> 日期: 2026-04-16
> 状态: ✅ 完成
> 目标: 实现 Skill 系统，支持 prompt 模板化 + 动态加载

---

## 1. 背景

Phase 4 让 CodeAgent 接入 LLM，但 system prompt 是硬编码的。Phase 5 的目标是：
- 把 system prompt 从硬编码改为可加载的 Skill
- Skill = prompt 模板 + 可选初始化脚本 + 每任务脚本
- 支持动态加载/卸载 Skills
- 根据任务描述自动匹配合适的 Skills

**参考文档：** `docs/architecture-design.md` 第 0 节

---

## 2. 目标

1. 实现 `Skill` / `SkillInstance` 数据模型
2. 实现 `SkillManager`，支持目录扫描 + YAML frontmatter 解析
3. 创建示例 Skills（python-expert、fastapi-expert）
4. 实现 Skill → CodeAgent system prompt 注入
5. 实现 `/skills` CLI 命令（list / load / unload / match）
6. 52 个单元测试，全部通过

---

## 3. 操作步骤

### 3.1 Skill 数据模型

文件路径: `src/lustre/skills/models.py`

```python
@dataclass
class Skill:
    name: str
    description: str
    prompt_template: str          # 支持 {variable} 占位符
    init_script: str | None       # 加载时运行一次
    task_script: str | None        # 每个任务前运行
    trigger_keywords: list[str]   # 自动匹配关键词
    variables: dict[str, str]     # 运行时填充变量

@dataclass
class SkillInstance:
    skill: Skill
    active: bool = True
    init_output: str | None       # init 脚本输出
```

### 3.2 SkillManager

文件路径: `src/lustre/skills/manager.py`

**搜索路径（优先级递减）：**
1. `~/.lustre/skills/` — 用户安装的 Skills
2. `<repo>/skills/` — 捆绑的 Skills

**SKILL.md 格式：**
```yaml
---
name: fastapi-expert
description: FastAPI 专家
version: 1.0.0
trigger_keywords: ["fastapi", "@app"]
---
## System Prompt
你是一个 FastAPI 专家...

## {custom_instructions}
```

**关键方法：**
- `discover()` — 扫描所有搜索路径
- `load_skill(name)` — 加载 Skill（运行 init_script）
- `unload_skill(name)` — 卸载
- `match_skills(task_desc)` — 根据 trigger_keywords 自动匹配

### 3.3 Skill 注入机制

文件路径: `src/lustre/agents/code_agent.py`

```python
def _build_system_prompt(self) -> str:
    parts = [self._system_prompt]  # base prompt
    for si in self._skills:
        if si.active:
            parts.append(f"

{'='*40}
")
            parts.append(f"# Skill: {si.name}
")
            parts.append(si.prompt)  # resolved prompt
    return "
".join(parts)
```

### 3.4 CLI /skills 命令

```
/skills              — 列出已加载的 Skills
/skills list        — 列出所有已发现的 Skills
/skills load <name> — 加载指定 Skill（自动重新构建 CodeAgent）
/skills unload <name> — 卸载指定 Skill
/skills match <text> — 显示哪些 Skills 会匹配任务描述
```

### 3.5 示例 Skills

**python-expert** (`skills/python-expert/SKILL.md`):
- 触发词: `["python", "py", "写python", "python代码"]`
- 内容: PEP 8 / 类型提示 / Docstring / 测试规范

**fastapi-expert** (`skills/fastapi-expert/SKILL.md`):
- 触发词: `["fastapi", "api route", "@app", "HTTP请求", "openapi"]`
- 内容: FastAPI 路由 / Pydantic / 依赖注入 / 错误处理

---

## 4. 目录结构

```
skills/
├── python-expert/
│   └── SKILL.md
└── fastapi-expert/
    └── SKILL.md

src/lustre/skills/
├── __init__.py
├── models.py       # Skill / SkillInstance 数据类
└── manager.py      # SkillManager

src/lustre/agents/
└── code_agent.py   # Skill 注入 + _build_system_prompt()
```

---

## 5. 关键设计决策

### 5.1 为什么用 YAML frontmatter 而不是纯 JSON？

SKILL.md 包含自由格式的 prompt 模板（markdown），YAML frontmatter 只存元数据。
这样 prompt 可以包含代码块、列表等 markdown 结构，无需转义。

### 5.2 init_script 做什么？

可选的 Python 脚本，在 Skill 首次加载时运行。
可以用于：
- 检查环境依赖（`pip list | grep fastapi`）
- 拉取外部资源
- 预热缓存

### 5.3 trigger_keywords 的匹配逻辑？

`match_skills()` 对加载的每个 Skill，检查任意 keyword 是否是任务描述的子串（不区分大小写）。
如果没有定义 trigger_keywords，该 Skill 始终匹配（默认 Skill）。

### 5.4 为什么 `_reload_code_agent()` 需要手动调用？

Skill 加载/卸载后，CodeAgent 的 `_executor` 需要用新的 system prompt 重新创建。
当前实现是停止旧 Agent → 用当前 Skills 创建新 Agent → 替换 `_supervisor.agents["code"]`。
未来可以用 Strategy 模式避免重建。

---

## 6. 遇到的问题与解决

### 6.1 YAML 解析遇到 `@` 字符

**问题：** `trigger_keywords: [fastapi, api route, @app]` 中 `@` 在 YAML 里是特殊字符，导致解析失败。

**解决：** 使用引号包裹含特殊字符的值：`["fastapi", "api route", "@app"]`。

### 6.2 `__slots__` 和 `cached_property` 不兼容

**问题：** Phase 4 ConfigLoader 中已遇到，同样问题出现在其他类。

**状态：** 已解决。

### 6.3 空 Skill 目录导致警告

**问题：** `skills/python-best-practices/` 目录存在但无 SKILL.md，discover 时每个目录都尝试加载并产生 WARNING 日志。

**解决：** 删除空目录，并确保 `_discover_skill_dirs()` 跳过无效目录只产生日志而不抛异常。

---

## 7. 验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|---------|
| Skill 发现 | `uv run python -c "from lustre.skills import SkillManager; sm=SkillManager(); sm.discover(); print(sm.list_skill_names())"` | `['fastapi-expert', 'python-expert']` |
| Skill 匹配 | `/skills match 帮我写一个 FastAPI` | `fastapi-expert` |
| Skill 加载 | `/skills load fastapi-expert` | `✓ 已加载 Skill: fastapi-expert` |
| `/skills` 表格 | `echo "/skills
/exit" \| uv run python -m lustre` | 显示表格 |
| /demo 流程 | `echo "/demo
/exit" \| uv run python -m lustre` | 完整流程完成 |
| 52 测试通过 | `uv run pytest tests/unit/ -q` | 52 passed |

---

## 8. 交付物

| 文件 | 路径 | 说明 |
|------|------|------|
| 数据模型 | `src/lustre/skills/models.py` | Skill / SkillInstance |
| Manager | `src/lustre/skills/manager.py` | 发现/加载/匹配 |
| Skill 示例 | `skills/python-expert/SKILL.md` | Python 专家 |
| Skill 示例 | `skills/fastapi-expert/SKILL.md` | FastAPI 专家 |
| CodeAgent 更新 | `src/lustre/agents/code_agent.py` | Skill 注入 |
| CLI 更新 | `src/lustre/cli.py` | /skills 命令 |
| 本文档 | `docs/phase-5-skill-system.md` | 操作记录 |

---

## 9. 下一步

Phase 5 ✅ 完成 → 进入 **Phase 6：内置工具（完整版）**

Phase 6 将实现：
- 完整的工具注册表（`tools/registry.py`）
- 工具按需加载（按配置文件启用/禁用）
- 工具调用结果的结构化返回
- 工具访问控制（哪些 Agent 能用哪些工具）
