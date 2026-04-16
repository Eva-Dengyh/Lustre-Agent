"""Lustre Agent CLI — Interactive shell for multi-agent coordination."""

import sys
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def print_banner() -> None:
    banner = Text()
    banner.append("Lustre Agent", style="bold gold1")
    banner.append(f"  v0.1.0", style="dim")

    panel = Panel(
        banner,
        title="Multi-Agent CLI Assistant",
        border_style="gold1",
        expand=False,
    )
    console.print(panel)


def print_ready() -> None:
    console.print("[dim][supervisor][/dim] Supervisor 就绪", style="green")
    console.print("[dim]输入 /help 查看命令，输入 /exit 退出[/dim]")


def print_help() -> None:
    """Print available CLI commands."""
    from rich.table import Table

    table = Table(title="可用命令", show_header=True, header_style="bold")
    table.add_column("命令", style="cyan", width=20)
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
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)


def main() -> None:
    """Main CLI entry point."""
    print_banner()

    # Phase 0: basic REPL, no agents yet
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
        elif cmd == "/help":
            print_help()
        elif cmd == "/new":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/status":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/go":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/abort":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/retry":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/skip":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/edit":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/bg":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd == "/jobs":
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        elif cmd.startswith("/kill"):
            console.print("[dim]功能开发中...（Phase 1+）[/dim]")
        else:
            console.print(f"[red]未知命令: {cmd}[/red]")
            console.print("输入 /help 查看可用命令")


if __name__ == "__main__":
    main()
