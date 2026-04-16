"""Lustre Agent CLI — Interactive shell for multi-agent coordination.

Phase 2: integrates the message bus and EchoAgent to demonstrate
the full "task dispatched → result received" flow without LLM calls.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from lustre.agents import SPECIALIST_AGENTS
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType, TaskRequest

console = Console()

# Shared bus instance (module-level for access from command handlers)
_bus: MemoryMessageBus | None = None
_running_agents: dict[str, object] = {}


# ---------------------------------------------------------------------------
# Banner / help
# ---------------------------------------------------------------------------

def print_banner() -> None:
    banner = Text()
    banner.append("Lustre Agent", style="bold gold1")
    banner.append(f"  v0.2.0", style="dim")

    panel = Panel(
        banner,
        title="Multi-Agent CLI Assistant",
        border_style="gold1",
        expand=False,
    )
    console.print(panel)


def print_help() -> None:
    from rich.table import Table

    table = Table(title="可用命令", show_header=True, header_style="bold")
    table.add_column("命令", style="cyan", width=22)
    table.add_column("说明")

    commands = [
        ("/help", "显示本帮助信息"),
        ("/exit", "退出 CLI"),
        ("/new", "开始新任务"),
        ("/status", "查看当前任务状态"),
        ("/go", "通过当前确认门，继续执行"),
        ("/abort", "取消当前任务"),
        ("/retry", "重试失败的上一步"),
        ("/skip", "跳过当前步骤"),
        ("/edit", "修改计划或任务描述"),
        ("/bg", "挂起任务到后台"),
        ("/jobs", "列出所有后台任务"),
        ("/kill <id>", "终止后台任务"),
        ("/demo", "运行总线演示（Phase 2 验证）"),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)


# ---------------------------------------------------------------------------
# Demo — verify bus + agent flow
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """Demonstrate: supervisor dispatches task → EchoAgent receives → returns result."""
    global _bus

    console.print("\n[bold]=== 总线演示 (Phase 2) ===[/bold]")
    console.print("流程: Supervisor → [总线] → CodeEchoAgent → [总线] → Supervisor\n")

    if _bus is None:
        _bus = MemoryMessageBus()

    # Start CodeEchoAgent
    from lustre.agents.echo_agent import CodeEchoAgent

    agent = CodeEchoAgent(bus=_bus)
    agent.start()
    console.print(f"[green]+[/green] CodeEchoAgent 已启动 (listening on task.code)")

    # Supervisor dispatches a task via bus
    task_id = f"task-{uuid.uuid4().hex[:6]}"
    conversation_id = f"conv-{uuid.uuid4().hex[:6]}"
    task_request = TaskRequest(
        task_id=task_id,
        description="Write a hello world FastAPI endpoint",
        context={"language": "python", "framework": "fastapi"},
        skills_requested=["python-best-practices"],
        confirmation_needed=False,
    )

    console.print(f"[yellow]→[/yellow] Supervisor 发送任务到总线:")
    console.print(f"       task_id={task_id}")
    console.print(f"       description={task_request.description}")

    # Supervisor waits for result
    result_received: list[Message] = []
    _bus.subscribe(f"result.{agent.name}", result_received.append)

    _bus.publish(
        f"task.{agent.name}",
        Message(
            sender="supervisor",
            type=MessageType.TASK_REQUEST,
            payload=task_request.to_dict(),
            conversation_id=conversation_id,
        ),
    )
    console.print("[yellow]→[/yellow] 等待 CodeEchoAgent 响应...")

    # Wait for result
    if not result_received:
        console.print("[red]✗ 超时，无响应[/red]")
        agent.stop()
        return

    result_msg = result_received[0]
    console.print(f"\n[green]✓[/green] CodeEchoAgent 响应:")
    console.print(f"       sender={result_msg.sender}")
    console.print(f"       status={result_msg.payload.get('status')}")
    console.print(f"       output={result_msg.payload.get('output')}")
    console.print(f"       reply_to={result_msg.reply_to}")

    agent.stop()
    console.print("[green]+[/green] CodeEchoAgent 已停止")
    console.print("\n[bold]=== 演示完成 ===[/bold]\n")


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def main() -> None:
    global _bus

    print_banner()

    # Initialise bus for this session
    _bus = MemoryMessageBus()
    console.print("[dim][supervisor][/dim] Supervisor 就绪", style="green")
    console.print("[dim]输入 /help 查看命令，输入 /exit 退出[/dim]\n")

    while True:
        try:
            user_input = console.input("\n[bold]>[/bold] ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]再见！[/yellow]")
            sys.exit(0)

        cmd = user_input.strip()

        if not cmd:
            continue

        if cmd == "/exit":
            console.print("[yellow]再见！[/yellow]")
            break

        if cmd == "/help":
            print_help()

        elif cmd == "/demo":
            run_demo()

        elif cmd in (
            "/new", "/status", "/go", "/abort", "/retry",
            "/skip", "/edit", "/bg", "/jobs",
        ):
            console.print(
                "[dim]功能开发中 (Phase 3+): "
                + cmd
                + "[/dim]"
            )

        elif cmd.startswith("/kill"):
            console.print("[dim]功能开发中 (Phase 3+)[/dim]")

        else:
            console.print(f"[red]未知命令: {cmd}[/red]")
            console.print("输入 /help 查看可用命令")


if __name__ == "__main__":
    main()
