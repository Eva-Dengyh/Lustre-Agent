import uuid

import typer
from rich.console import Console
from rich.markdown import Markdown

from .llm import get_llm

app = typer.Typer(help="Lustre Agent CLI")
console = Console()


# ── default: enter chat REPL when no subcommand ──────────────────────────────

@app.callback(invoke_without_command=True)
def default(ctx: typer.Context):
    """进入聊天 REPL（默认）"""
    if ctx.invoked_subcommand is None:
        _chat_repl()


def _chat_repl():
    from prompt_toolkit import prompt as pt_prompt
    from langchain_core.messages import HumanMessage
    from .graph import build_graph
    from .memory import list_thread_ids

    graph = build_graph()
    thread_id = str(uuid.uuid4())

    console.print(
        f"[bold green]Lustre[/bold green]  "
        f"thread [dim]{thread_id[:8]}[/dim]  "
        "[dim]/history  /replay <id>  /new  /exit[/dim]"
    )

    while True:
        try:
            user_input = pt_prompt("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            break

        if not user_input:
            continue

        if user_input == "/exit":
            console.print("[dim]Bye.[/dim]")
            break
        elif user_input == "/history":
            ids = list_thread_ids()
            if not ids:
                console.print("[dim]No history yet.[/dim]")
            else:
                for tid in ids:
                    marker = " [bold green]← current[/bold green]" if tid == thread_id else ""
                    console.print(f"  [cyan]{tid}[/cyan]{marker}")
        elif user_input.startswith("/replay "):
            tid = user_input[len("/replay "):].strip()
            _print_thread(graph, tid)
        elif user_input == "/new":
            thread_id = str(uuid.uuid4())
            console.print(f"[dim]New thread: {thread_id[:8]}[/dim]")
        else:
            config = {"configurable": {"thread_id": thread_id}}
            result = graph.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )
            ai_msg = result["messages"][-1]
            console.print(Markdown(ai_msg.content))


def _print_thread(graph, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config)
    if not state or not state.values:
        console.print(f"[red]Thread not found:[/red] {thread_id}")
        return
    msgs = state.values.get("messages", [])
    if not msgs:
        console.print("[dim]Empty thread.[/dim]")
        return
    console.print(f"\n[bold]Thread {thread_id[:8]}[/bold]")
    for msg in msgs:
        role = "[bold cyan]You[/bold cyan]" if msg.type == "human" else "[bold green]AI[/bold green]"
        console.print(f"{role}: {msg.content}")
    console.print()


# ── named subcommands ─────────────────────────────────────────────────────────

@app.command()
def hello():
    """最小 LLM 调用演示（Day 1）"""
    llm = get_llm()
    response = llm.invoke("Say hi in one sentence")
    typer.echo(response.content)


@app.command()
def replay(thread_id: str = typer.Argument(..., help="Thread ID to replay")):
    """打印指定会话的完整对话"""
    from .graph import build_graph
    graph = build_graph()
    _print_thread(graph, thread_id)


@app.command()
def version():
    """显示版本信息"""
    typer.echo("lustre-agent 0.1.0")


if __name__ == "__main__":
    app()
