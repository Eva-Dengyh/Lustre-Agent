"""Lustre Agent CLI — Interactive shell for multi-agent coordination.

Phase 3: integrates Supervisor + Planner + Specialist agents.
Demonstrates: user request → plan → confirmation → agent execution → result.
"""

from __future__ import annotations

import sys
import threading
import uuid
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lustre.agents import SPECIALIST_AGENTS
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.bus.message import Message, MessageType
from lustre.supervisor import (
    ExecutionPlan,
    Planner,
    Supervisor,
    SupervisorState,
)

console = Console()
_bus: MemoryMessageBus | None = None
_supervisor: Supervisor | None = None


# ---------------------------------------------------------------------------
# Banner / help
# ---------------------------------------------------------------------------

def print_banner() -> None:
    banner = Text()
    banner.append("Lustre Agent", style="bold gold1")
    banner.append("  v0.3.0", style="dim")
    panel = Panel(
        banner,
        title="Multi-Agent CLI Assistant",
        border_style="gold1",
        expand=False,
    )
    console.print(panel)


def print_help() -> None:
    table = Table(title="可用命令", show_header=True, header_style="bold")
    table.add_column("命令", style="cyan", width=24)
    table.add_column("说明")

    commands = [
        ("/help", "显示本帮助信息"),
        ("/exit", "退出 CLI"),
        ("/new", "开始新任务（输入需求）"),
        ("/status", "查看当前任务状态"),
        ("/go", "通过当前确认门，继续执行"),
        ("/abort", "取消当前任务"),
        ("/retry", "重试失败的上一步"),
        ("/skip", "跳过当前步骤"),
        ("/edit", "修改计划或任务描述"),
        ("/bg", "挂起任务到后台"),
        ("/jobs", "列出所有后台任务"),
        ("/kill <id>", "终止后台任务"),
        ("/demo", "运行交互演示"),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)


# ---------------------------------------------------------------------------
# Supervisor setup
# ---------------------------------------------------------------------------

def _setup_supervisor() -> Supervisor:
    """Create and start the supervisor with all registered specialist agents."""
    global _bus

    if _bus is None:
        _bus = MemoryMessageBus()

    # Instantiate all registered specialist agents
    agents: dict[str, object] = {}
    for name, agent_cls in SPECIALIST_AGENTS.items():
        agent = agent_cls(bus=_bus)
        agent.start()
        agents[name] = agent

    sup = Supervisor(bus=_bus, agents=agents)

    # Set up UI callbacks
    def on_confirmation(plan: ExecutionPlan) -> None:
        _print_plan_confirmation(plan)

    def on_step_complete(step_data: dict) -> None:
        _print_step_complete(step_data)

    def on_task_complete(ctx_data: dict) -> None:
        _print_task_complete(ctx_data)

    sup.on_confirmation_needed = on_confirmation
    sup.on_step_complete = on_step_complete
    sup.on_task_complete = on_task_complete

    sup.start()
    return sup


def _teardown_supervisor() -> None:
    global _supervisor
    if _supervisor:
        _supervisor.stop()
        _supervisor = None


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _print_plan(plan: ExecutionPlan) -> None:
    """Print a plan in a formatted table."""
    console.print(f"\n[bold]任务计划 (共 {len(plan.steps)} 步)[/bold]")
    console.print(f"[dim]请求: {plan.original_request}[/dim]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("步骤", style="cyan", width=3)
    table.add_column("描述", style="white")
    table.add_column("Agent", style="green", width=10)
    table.add_column("状态", style="yellow", width=10)

    for i, step in enumerate(plan.steps, 1):
        status_map = {
            "pending": "[dim]待执行[/dim]",
            "running": "[yellow]执行中[/yellow]",
            "completed": "[green]已完成[/green]",
            "failed": "[red]失败[/red]",
            "skipped": "[dim]已跳过[/dim]",
        }
        status_str = status_map.get(step.status, step.status)
        table.add_row(str(i), step.description, step.agent_name, status_str)

    console.print(table)


def _print_plan_confirmation(plan: ExecutionPlan) -> None:
    """Print the plan and prompt for confirmation."""
    _print_plan(plan)
    console.print()
    console.print("[bold yellow]⚠️  确认计划[/bold yellow]")
    console.print("  输入 [green]/go[/green] 继续执行")
    console.print("  输入 [cyan]/edit[/cyan] 修改计划")
    console.print("  输入 [red]/abort[/red] 取消任务")


def _print_step_complete(step_data: dict) -> None:
    """Print step completion info."""
    status = step_data.get("status", "?")
    desc = step_data.get("description", "?")
    result = step_data.get("result", "")
    error = step_data.get("error")

    status_color = {
        "completed": "green",
        "failed": "red",
        "skipped": "dim",
    }.get(status, "yellow")

    icon = {
        "completed": "✅",
        "failed": "❌",
        "skipped": "⏭",
    }.get(status, "🔄")

    console.print(f"\n{icon} [{status_color}]{status.upper()}[/{status_color}] {desc}")
    if result:
        for line in result.split("\n")[:5]:
            console.print(f"   {line}")
    if error:
        console.print(f"   [red]错误: {error}[/red]")


def _print_task_complete(ctx_data: dict) -> None:
    """Print final task completion summary."""
    plan = ctx_data.get("plan")
    if not plan:
        return

    console.print("\n[bold gold1]═══════════════════════════════════════[/bold gold1]")
    console.print("[bold green]✅ 任务完成[/bold green]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("步骤", style="cyan", width=3)
    table.add_column("Agent", style="green", width=10)
    table.add_column("状态", width=12)

    for i, step_data in enumerate(plan.get("steps", []), 1):
        status = step_data.get("status", "?")
        status_color = {
            "completed": "green",
            "failed": "red",
            "skipped": "dim",
        }.get(status, "yellow")
        table.add_row(
            str(i),
            step_data.get("agent_name", "?"),
            f"[{status_color}]{status}[/{status_color}]",
        )

    console.print(table)

    failed = [s for s in plan.get("steps", []) if s.get("status") == "failed"]
    if failed:
        console.print(f"\n[red]⚠️  {len(failed)} 个步骤失败[/red]")
        for s in failed:
            console.print(f"   - {s.get('description')}: {s.get('error')}")


def _print_status() -> None:
    """Print current task status."""
    if _supervisor is None:
        console.print("[dim]Supervisor 未初始化[/dim]")
        return

    state = _supervisor.state
    ctx = _supervisor.context

    state_color = {
        SupervisorState.IDLE: "dim",
        SupervisorState.PLANNING: "yellow",
        SupervisorState.AWAITING_CONFIRMATION: "bold yellow",
        SupervisorState.EXECUTING: "cyan",
        SupervisorState.DONE: "green",
        SupervisorState.ABORTED: "red",
    }.get(state, "white")

    console.print(f"状态: [{state_color}]{state.value}[/{state_color}]")

    if ctx.user_request:
        console.print(f"请求: {ctx.user_request}")

    if _supervisor.plan:
        _print_plan(_supervisor.plan)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """Run an interactive demonstration of the full workflow."""
    global _supervisor

    console.print("\n[bold]=== Phase 3 交互演示 ===[/bold]\n")

    _supervisor = _setup_supervisor()

    # Step 1: submit a task
    console.print("[cyan]1. 提交任务...[/cyan]")
    plan = _supervisor.submit(
        "帮我调研 FastAPI 和 Flask，然后写一个 hello world API"
    )
    console.print(f"[green]✓[/green] 计划已生成 ({len(plan.steps)} 步)，等待确认...\n")

    # Step 2: confirm plan and auto-handle confirmation gates
    console.print("[cyan]2. 用户确认计划 (simulate /go)...[/cyan]\n")

    # Kick off execution (AWAITING_CONFIRMATION → EXECUTING via confirm_plan)
    _supervisor.confirm_plan()

    import time

    states_seen = []
    for _ in range(60):  # up to 12s
        state = _supervisor.state
        if state not in states_seen:
            states_seen.append(state)
            console.print(f"[dim]  state changed to: {state.value}[/dim]")
        time.sleep(0.2)

        if state == SupervisorState.DONE:
            break
        if state == SupervisorState.ABORTED:
            break

        if state == SupervisorState.AWAITING_CONFIRMATION:
            _supervisor.confirm_and_continue()

    console.print("\n[bold]=== 演示结束 ===[/bold]\n")

    _teardown_supervisor()


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def main() -> None:
    global _supervisor, _bus

    print_banner()

    # Initialise bus and supervisor for this session
    _bus = MemoryMessageBus()
    _supervisor = _setup_supervisor()

    console.print("[dim][supervisor][/dim] Supervisor 就绪", style="green")
    console.print("[dim]输入 /help 查看命令，输入 /exit 退出[/dim]\n")

    while True:
        try:
            user_input = console.input("\n[bold]>[/bold] ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]再见！[/yellow]")
            _teardown_supervisor()
            sys.exit(0)

        cmd = user_input.strip()

        if not cmd:
            continue

        if cmd == "/exit":
            console.print("[yellow]再见！[/yellow]")
            _teardown_supervisor()
            break

        if cmd == "/help":
            print_help()

        elif cmd == "/demo":
            run_demo()

        elif cmd == "/status":
            _print_status()

        elif cmd == "/new":
            console.print("[dim]请直接输入你的需求（相当于 /new）[/dim]")
            console.print("[dim]例如: 帮我写一个 FastAPI hello world[/dim]")

        elif cmd == "/go":
            if _supervisor and _supervisor.state == SupervisorState.AWAITING_CONFIRMATION:
                _supervisor.confirm_plan()
                console.print("[green]执行中...[/green]")
            else:
                console.print("[dim]当前没有等待确认的计划[/dim]")

        elif cmd == "/abort":
            if _supervisor:
                _supervisor.request_abort()
                console.print("[yellow]任务已取消[/yellow]")
                _teardown_supervisor()
                _bus = MemoryMessageBus()
                _supervisor = _setup_supervisor()

        elif cmd == "/retry":
            if _supervisor:
                _supervisor.retry_current_step()

        elif cmd == "/skip":
            if _supervisor:
                _supervisor.skip_current_step()

        elif cmd == "/edit":
            console.print("[dim]功能开发中 (Phase 5+)[/dim]")

        elif cmd in ("/bg", "/jobs", "/kill"):
            console.print("[dim]功能开发中 (Phase 5+)[/dim]")

        elif not cmd.startswith("/"):
            # Free-text input treated as a new task request
            if _supervisor and _supervisor.state == SupervisorState.IDLE:
                try:
                    plan = _supervisor.submit(cmd)
                    _print_plan_confirmation(plan)
                except Exception as exc:
                    console.print(f"[red]错误: {exc}[/red]")
            else:
                console.print(
                    "[dim]当前有任务进行中，请先 /abort 后再提交新任务[/dim]"
                )

        else:
            console.print(f"[red]未知命令: {cmd}[/red]")
            console.print("输入 /help 查看可用命令")


if __name__ == "__main__":
    main()
