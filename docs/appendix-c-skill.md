---
appendix: C
title: "Skill 能力包"
status: draft
est_minutes: 90
depends_on: [day4]
---

# Appendix C · Skill 能力包

> 把"prompt + tool 列表 + 验收策略"打包成可加载的 Skill，让 Lustre-Agent 在不同领域秒变专业 agent。

## 0. 30 秒速览

- **为什么**：通用 agent 在专业领域往往不如"内置 SOP + 专用工具"的窄 agent；Skill 就是这种封装的最小单元
- **做什么**：定义 Skill 文件结构（一个目录 + `skill.yaml` + 可选脚本/prompt），实现 `/skill load <name>`、`/skill list`
- **类比**：类似 Claude Code 的 Skill；本附录是一个轻量本地版

## 1. 概念

- **Skill = 配置 + Prompt + 工具组**：声明性，不写一行 LangGraph 代码就能"换皮"
- **加载机制**：从 `~/.lustre/skills/` 与 `./skills/` 各扫一遍；后者优先
- **作用域**：load 后只在当前 thread 生效（不污染默认 chat agent）

## 2. 前置条件

- 已完成 Day 4
- 新增依赖：`pyyaml`

## 3. 目标产物

```tree
src/lustre_agent/
├── skills/
│   ├── __init__.py
│   ├── loader.py            ← 新增：扫描 + 解析 skill.yaml
│   └── runtime.py           ← 新增：把 Skill 应用到当前 graph state
├── cli.py                   ← 修改：/skill 子命令
skills/                      ← 项目自带的示例 skill
└── pytest-pro/
    ├── skill.yaml
    └── prompt.md
tests/
└── appendix_c_smoke.py
```

`skill.yaml` schema 示例：

```yaml
name: pytest-pro
description: "为 Python 项目编写高质量 pytest 测试的 skill"
version: 0.1.0
prompt: prompt.md
tools:                  # 引用 Lustre 内置/MCP 工具的名字
  - read_file
  - write_file
  - run_shell
  - filesystem.list_directory   # MCP 工具示例
acceptance:             # 可选：被 Reviewer 注入
  - "新增/修改的测试必须能用 pytest 收集到"
  - "覆盖至少一个 happy-path 与一个 edge case"
```

## 4. 实现步骤

### Step 1 — Loader

- 扫描两个目录；解析 yaml；校验字段
- 暴露 `list_skills()`、`load_skill(name) -> Skill`

### Step 2 — Runtime 应用

- 当前 thread 的 State 里加 `active_skill: Skill | None`
- Coder/Reviewer 节点构 prompt 时检查 `active_skill`，若有则：
  - 把 `prompt.md` 的内容追加到 system
  - tools 过滤为 skill.tools 的子集
  - acceptance 注入 Reviewer 的判据列表

### Step 3 — CLI

- `/skill list`、`/skill load <name>`、`/skill unload`
- REPL prompt 行显示当前激活 skill 名

## 5. 关键代码骨架

```python
# src/lustre_agent/skills/loader.py
from pydantic import BaseModel
class Skill(BaseModel):
    name: str
    description: str
    version: str
    prompt: str          # 已读入的内容
    tools: list[str]
    acceptance: list[str] = []
def list_skills() -> list[Skill]: ...
def load_skill(name: str) -> Skill: ...
```

## 6. 验收

```bash
uv run lustre
> /skill list
# pytest-pro  v0.1.0  为 Python 项目编写高质量 pytest 测试
> /skill load pytest-pro
> /code 给 src/lustre_agent/tools/fs.py 写测试
# Coder 应只用列出的 tools；Reviewer 检查会引用 skill 的 acceptance
```

自动：`uv run pytest tests/appendix_c_smoke.py -v`

## 7. 常见坑

- Skill 越多越混乱：建议每个 skill 单一职责
- tools 引用的 MCP 工具未连接：load 时校验，缺失则警告并降级
- 提示词冲突：skill prompt 与默认 prompt 拼接时要明确分段（如 `## SKILL OVERLAY`）
