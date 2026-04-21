---
appendix: B
title: "MCP 接入"
status: draft
est_minutes: 90
depends_on: [day3]
---

# Appendix B · MCP 接入

> 让 Lustre-Agent 的 Coder 可以直接使用任何 MCP server 的工具（文件系统、浏览器、数据库、GitHub 等等），而不用我们自己一个个写。

## 0. 30 秒速览

- **为什么**：MCP（Model Context Protocol）是 2025 年后事实标准的"工具/资源"协议；别人已经写好的 server 拿来就用
- **做什么**：加一个 `mcp_loader`，启动时从 `lustre.mcp.json` 读配置，拉起/连接 MCP server，把它们的 tools 合并进 Lustre 的 tool 列表
- **不做什么**：不实现 MCP server（那是 `mcp-builder` skill 的事）

## 1. 概念

- **MCP client**：用官方 `mcp` Python SDK；走 stdio/WebSocket/HTTP 传输
- **工具发现**：连接后调用 `list_tools()` 拿到工具 schema
- **schema 对齐**：MCP 的工具 schema = JSON Schema，天然能被 LangChain tool 包装
- **生命周期**：MCP server 是子进程/远端服务，Lustre 启动时连接、退出时断开

## 2. 前置条件

- 已完成 Day 3（tool 抽象存在）
- 新增依赖：`mcp`（官方 SDK）

## 3. 目标产物

```tree
src/lustre_agent/
├── tools/
│   ├── mcp_loader.py        ← 新增：加载配置 + 包装为 LangChain tools
│   └── __init__.py          ← 修改：合并 MCP tools 到 ALL_TOOLS
lustre.mcp.json              ← 新增（用户自己维护；示例）
tests/
└── appendix_b_smoke.py      ← 新增（用 mock MCP server）
```

`lustre.mcp.json` 示例：

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/eva/code"],
      "enabled": true
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" },
      "enabled": false
    }
  }
}
```

## 4. 实现步骤

### Step 1 — 解析配置

- 读 `lustre.mcp.json`；支持 `${ENV}` 变量替换

### Step 2 — 建立连接

- 对每个 enabled server 调 `stdio_client()` 建立 session；启动时全连上
- 退出时 `await session.close()`

### Step 3 — 工具包装

- `list_tools()` 返回的每个 tool → LangChain `StructuredTool.from_function(...)`
- 工具名空间化：`<server>.<tool>`（避免冲突）

### Step 4 — 注册进 ALL_TOOLS

- `register_mcp_tools()` 在 `tools/__init__.py` 启动路径里被调用
- Coder / Chat agent 重建 `bind_tools`

### Step 5 — CLI 命令

- `/mcp list`：列出连接的 server + 工具数
- `/mcp reload`：重载配置

## 5. 关键代码骨架

```python
# src/lustre_agent/tools/mcp_loader.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import StructuredTool

async def connect_server(name, cfg): ...
def wrap_as_langchain_tool(session, tool_schema) -> StructuredTool: ...
def register_mcp_tools() -> list[StructuredTool]: ...
```

## 6. 验收

```bash
# 1) 在 lustre.mcp.json 里启用 filesystem server
uv run lustre
> /mcp list
# 预期：filesystem ✓ 5 tools
> /code 列出 /Users/eva/code/Lustre-Agent 下的 md 文件
# Coder 调用 filesystem.list_directory
```

自动：`uv run pytest tests/appendix_b_smoke.py -v`（用 mock server 验证挂载流程）

## 7. 常见坑

- MCP server 启动慢，第一次 CLI 冷启动变长 → 加进度条
- Tool schema 复杂对象在 LangChain 绑定时可能需要扁平化
- 权限：filesystem server 要限定根目录，不要给整个 `/`
