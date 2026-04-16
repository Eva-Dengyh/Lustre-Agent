"""Lustre Agent CLI — Interactive shell for multi-agent coordination.

Phase 5: integrates Skill system.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure lustre package is importable
if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lustre.agents.base import AgentConfig, SpecialistAgent
from lustre.agents.code_agent import CodeAgent
from lustre.bus.memory_bus import MemoryMessageBus
from lustre.config.loader import load_config
from lustre.session import SessionManager
from lustre.skills import SkillManager
from lustre.skills.models import SkillInstance
from lustre.supervisor import (
    ExecutionPlan,
    Supervisor,
    SupervisorState,
)

console = Console()
_bus: MemoryMessageBus | None = None
_supervisor: Supervisor | None = None
_config = None
_skill_manager: SkillManager | None = None
_session_manager: SessionManager | None = None


# ---------------------------------------------------------------------------
# Banner / help
# ---------------------------------------------------------------------------

def print_banner() -> None:
    v = _config.version if _config else "0.5.0"
    banner = Text()
    banner.append("Lustre Agent", style="bold gold1")
    banner.append(f"  v{v}", style="dim")
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
        ("/skills", "查看已加载的 Skills"),
        ("/skills load <name>", "加载指定 Skill"),
        ("/skills unload <name>", "卸载指定 Skill"),
        ("/sessions", "查看所有会话"),
        ("/sessions new <标题>", "创建新会话"),
        ("/sessions switch <id>", "切换到指定会话"),
        ("/sessions search <关键词>", "搜索会话内容"),
        ("/demo", "运行交互演示（Echo 模式，无 LLM）"),
    ]

    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)


# ---------------------------------------------------------------------------
# SkillManager setup
# ---------------------------------------------------------------------------

def _setup_skills() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
        _skill_manager.discover()
        _skill_manager.load_all()
        _print_skills_banner()
    return _skill_manager


def _print_skills_banner() -> None:
    if not _skill_manager:
        return
    names = _skill_manager.list_skill_names()
    if names:
        console.print(f"[dim]已加载 {len(names)} 个 Skills: {', '.join(names)}[/dim]")


# ---------------------------------------------------------------------------
# Agent factory (with Skill injection)
# ---------------------------------------------------------------------------

def _create_agents(bus: MemoryMessageBus) -> dict[str, SpecialistAgent]:
    """Create specialist agents, using LLM CodeAgent if API key is available."""
    cfg = _config
    sm = _skill_manager
    agents: dict[str, SpecialistAgent] = {}

    # CodeAgent — use real LLM if ANTHROPIC_API_KEY is set
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key and cfg:
        code_cfg = cfg.agents.get("code", {})
        agent_cfg = AgentConfig(
            name="code",
            model_provider=code_cfg.get("model_provider", "anthropic"),
            model_name=code_cfg.get("model_name", "claude-sonnet-4-6"),
            api_key=api_key,
        )
        # Inject matched skills
        skills: list[SkillInstance] = []
        if sm:
            skills = sm.get_loaded()
        code_agent = CodeAgent(config=agent_cfg, bus=bus, skills=skills)
        code_agent.start()
        agents["code"] = code_agent
        console.print(f"[dim]CodeAgent (LLM): {agent_cfg.model_name}[/dim]")
    else:
        # Fall back to echo
        from lustre.agents.echo_agent import CodeEchoAgent
        echo_agent = CodeEchoAgent(bus=bus)
        echo_agent.start()
        agents["code"] = echo_agent
        console.print("[dim]CodeAgent (Echo 模式)[/dim]")

    # Echo agents for research/test
    from lustre.agents.echo_agent import EchoAgent
    research_cfg = AgentConfig(name="research", description="Research agent")
    research_impl = EchoAgent(config=research_cfg, bus=bus)
    research_impl.start()
    agents["research"] = research_impl

    test_cfg = AgentConfig(name="test", description="Test agent")
    test_impl = EchoAgent(config=test_cfg, bus=bus)
    test_impl.start()
    agents["test"] = test_impl

    return agents


# ---------------------------------------------------------------------------
# Supervisor lifecycle
# ---------------------------------------------------------------------------

def _setup_supervisor() -> Supervisor:
    global _bus, _supervisor

    if _bus is None:
        _bus = MemoryMessageBus()

    agents = _create_agents(_bus)
    sup = Supervisor(bus=_bus, agents=agents)

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
    _print_plan(plan)
    console.print()
    console.print("[bold yellow]⚠️  确认计划[/bold yellow]")
    console.print("  输入 [green]/go[/green] 继续执行")
    console.print("  输入 [cyan]/edit[/cyan] 修改计划")
    console.print("  输入 [red]/abort[/red] 取消任务")


def _print_step_complete(step_data: dict) -> None:
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
        for line in result.split("\n")[:8]:
            console.print(f"   {line}")
    if error:
        console.print(f"   [red]错误: {error}[/red]")


def _print_task_complete(ctx_data: dict) -> None:
    plan = ctx_data.get("plan")
    if not plan:
        return

    console.print("\n[bold gold1]" + "═" * 40 + "[/bold gold1]")
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
# Skills commands
# ---------------------------------------------------------------------------

def _cmd_skills(args: list[str]) -> None:
    """Handle /skills command and its subcommands."""
    if not _skill_manager:
        _setup_skills()

    if not args:
        # List all loaded skills
        loaded = _skill_manager.get_loaded()
        discovered = _skill_manager.list_skill_names()

        console.print("\n[bold]Skills 状态[/bold]")
        console.print(f"已发现: [cyan]{len(discovered)}[/cyan] 个")
        console.print(f"已加载: [green]{len(loaded)}[/green] 个")

        if loaded:
            table = Table(title="已加载的 Skills", show_header=True)
            table.add_column("名称", style="cyan")
            table.add_column("描述", style="white")
            table.add_column("触发词", style="dim")
            table.add_column("版本", style="dim", width=8)

            for si in loaded:
                s = si.skill
                table.add_row(
                    s.name,
                    s.description[:50],
                    ", ".join(s.trigger_keywords[:3]),
                    s.version,
                )
            console.print(table)
        else:
            console.print("[dim]无已加载 Skills[/dim]")
        return

    subcmd = args[0]

    if subcmd == "load":
        if len(args) < 2:
            console.print("[red]用法: /skills load <skill_name>[/red]")
            return
        name = args[1]
        instance = _skill_manager.load_skill(name)
        if instance:
            console.print(f"[green]✓[/green] 已加载 Skill: {name}")
            # Reload CodeAgent with new skills
            _reload_code_agent()
        else:
            console.print(f"[red]✗[/red] 未找到 Skill: {name}")
            console.print(f"  可用: {', '.join(_skill_manager.list_skill_names())}")

    elif subcmd == "unload":
        if len(args) < 2:
            console.print("[red]用法: /skills unload <skill_name>[/red]")
            return
        name = args[1]
        _skill_manager.unload_skill(name)
        console.print(f"[green]✓[/green] 已卸载 Skill: {name}")
        _reload_code_agent()

    elif subcmd == "list":
        discovered = _skill_manager.list_skill_names()
        console.print("\n[bold]所有已发现的 Skills[/bold]")
        if not discovered:
            console.print("[dim]无[/dim]")
        for name in discovered:
            s = _skill_manager.get_skill(name)
            loaded_tag = "[green]●[/green]" if _skill_manager.is_loaded(name) else "[dim]○[/dim]"
            console.print(f"  {loaded_tag} {name}: {s.description if s else ''}")
        console.print(f"\n共 {len(discovered)} 个 Skill")

    elif subcmd == "match":
        # Show which skills would match a given task description
        if len(args) < 2:
            console.print("[red]用法: /skills match <task_description>[/red]")
            return
        task_desc = " ".join(args[1:])
        matched = _skill_manager.match_skills(task_desc)
        console.print(f"\n[bold]匹配结果[/bold] — {len(matched)} 个 Skill 匹配")
        for si in matched:
            console.print(f"  [green]✓[/green] {si.name}")
            console.print(f"       {si.skill.description}")
        if not matched:
            console.print("[dim]无匹配[/dim]")

    else:
        console.print(f"[red]未知子命令: {subcmd}[/red]")
        console.print("/skills [load <name>|unload <name>|list|match <text>]")


# ---------------------------------------------------------------------------
# Sessions commands
# ---------------------------------------------------------------------------

def _cmd_sessions(args: list[str]) -> None:
    """Handle /sessions command and its subcommands."""
    global _session_manager
    if _session_manager is None:
        console.print("[dim]Session 系统未初始化[/dim]")
        return

    if not args:
        # List all sessions
        sessions = _session_manager.list_sessions(limit=20)
        console.print("\n[bold]会话列表[/bold]")
        if not sessions:
            console.print("[dim]无会话记录[/dim]")
            return

        active_id = _session_manager.active_session_id
        table = Table(show_header=True, header_style="bold")
        table.add_column("", width=1)
        table.add_column("ID", style="dim", width=10)
        table.add_column("标题", style="white")
        table.add_column("消息数", style="cyan", width=8)
        table.add_column("最后更新", style="dim")

        for s in sessions:
            tag = "[green]●[/green]" if s.id == active_id else " "
            from lustre.session import SessionStore
            store = SessionStore()
            msg_count = store.count_messages(s.id)
            updated = s.updated_at[:16] if s.updated_at else ""
            table.add_row(tag, s.id[:8], s.title, str(msg_count), updated)

        console.print(table)
        return

    subcmd = args[0]

    if subcmd == "new":
        title = " ".join(args[1:]) if len(args) > 1 else "新会话"
        s = _session_manager.create_session(title=title)
        console.print(f"[green]✓[/green] 创建会话: {s.title} (ID: {s.id[:8]})")

    elif subcmd == "switch":
        if len(args) < 2:
            console.print("[red]用法: /sessions switch <id>[/red]")
            return
        sid = args[1]
        s = _session_manager.switch_session(sid)
        if s:
            console.print(f"[green]✓[/green] 切换到: {s.title}")
        else:
            console.print(f"[red]未找到会话: {sid}[/red]")

    elif subcmd == "delete":
        if len(args) < 2:
            console.print("[red]用法: /sessions delete <id>[/red]")
            return
        sid = args[1]
        if _session_manager.delete_session(sid):
            console.print(f"[green]✓[/green] 已删除: {sid[:8]}")
        else:
            console.print(f"[red]未找到会话: {sid}[/red]")

    elif subcmd == "rename":
        if len(args) < 3:
            console.print("[red]用法: /sessions rename <id> <新标题>[/red]")
            return
        sid = args[1]
        new_title = " ".join(args[2:])
        if _session_manager.rename_session(sid, new_title):
            console.print(f"[green]✓[/green] 已重命名: {new_title}")
        else:
            console.print(f"[red]未找到会话: {sid}[/red]")

    elif subcmd == "search":
        if len(args) < 2:
            console.print("[red]用法: /sessions search <关键词>[/red]")
            return
        query = " ".join(args[1:])
        results = _session_manager.search(query, limit=10)
        console.print(f"\n[bold]搜索结果: {query!r}[/bold]")
        if not results:
            console.print("[dim]无结果[/dim]")
        for r in results:
            role_tag = f"[{r['role']}]"
            content = r["content"][:100]
            console.print(f"  {role_tag} {content}")

    else:
        console.print(f"[red]未知子命令: {subcmd}[/red]")
        console.print("/sessions [new|title|switch <id>|delete <id>|rename <id> <title>|search <text>]")


def _reload_code_agent() -> None:
    """Stop current CodeAgent and restart with current skills."""
    global _supervisor
    if _supervisor is None:
        return
    # Replace code agent
    code_agent = _supervisor.agents.get("code")
    if code_agent:
        code_agent.stop()
    # Reload from factory with current skills
    if _skill_manager and _skill_manager.get_loaded():
        new_code = _create_code_agent_with_skills()
        if new_code:
            _supervisor.agents["code"] = new_code
            console.print("[dim]CodeAgent 已更新（包含当前 Skills）[/dim]")


def _create_code_agent_with_skills() -> SpecialistAgent | None:
    """Create a new CodeAgent with the current skill set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not _config:
        return None
    code_cfg = _config.agents.get("code", {})
    agent_cfg = AgentConfig(
        name="code",
        model_provider=code_cfg.get("model_provider", "anthropic"),
        model_name=code_cfg.get("model_name", "claude-sonnet-4-6"),
        api_key=api_key,
    )
    skills = _skill_manager.get_loaded() if _skill_manager else []
    code_agent = CodeAgent(config=agent_cfg, bus=_bus, skills=skills)
    code_agent.start()
    return code_agent


# ---------------------------------------------------------------------------
# Demo (Echo mode)
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """Run an interactive demonstration using EchoAgents (no LLM needed)."""
    global _supervisor

    console.print("\n[bold]=== Phase 7 交互演示 (Echo 模式) ===[/bold]\n")
    console.print("[dim]Skills: python-expert, fastapi-expert 已加载[/dim]\n")

    _demo_bus = MemoryMessageBus()

    from lustre.agents.echo_agent import CodeEchoAgent, EchoAgent
    from lustre.agents.base import AgentConfig

    echo_agents: dict[str, SpecialistAgent] = {}

    code_echo = CodeEchoAgent(bus=_demo_bus)
    code_echo.start()
    echo_agents["code"] = code_echo

    research_cfg = AgentConfig(name="research", description="Research echo agent")
    research_impl = EchoAgent(config=research_cfg, bus=_demo_bus)
    research_impl.start()
    echo_agents["research"] = research_impl

    test_cfg = AgentConfig(name="test", description="Test echo agent")
    test_impl = EchoAgent(config=test_cfg, bus=_demo_bus)
    test_impl.start()
    echo_agents["test"] = test_impl

    sup = Supervisor(bus=_demo_bus, agents=echo_agents)

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

    import time

    plan = sup.submit("调研 FastAPI 和 Flask，然后写一个 hello world API")
    console.print(f"[green]✓[/green] 计划已生成 ({len(plan.steps)} 步)\n")

    sup.confirm_plan()

    for _ in range(60):
        state = sup.state
        time.sleep(0.2)
        if state == SupervisorState.DONE:
            break
        if state == SupervisorState.ABORTED:
            break
        if state == SupervisorState.AWAITING_CONFIRMATION:
            sup.confirm_and_continue()

    sup.stop()
    console.print("\n[bold]=== 演示结束 ===[/bold]\n")


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def main() -> None:
    global _supervisor, _config

    # Load config first
    try:
        _config = load_config()
    except FileNotFoundError:
        console.print("[yellow]警告: 未找到配置文件，使用默认配置[/yellow]")
        _config = None

    print_banner()
    console.print("[dim]输入 /help 查看命令[/dim]\n")

    # Setup skills first (so CodeAgent can use them)
    _setup_skills()

    # Initialise session manager
    global _session_manager
    _session_manager = SessionManager()
    _session_manager.create_session(title="默认会话")
    console.print("[green]✓[/green] Session 系统就绪\n")

    # Initialise bus and supervisor
    _bus = MemoryMessageBus()
    _supervisor = _setup_supervisor()
    console.print("[green]✓[/green] Supervisor 就绪\n")

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

        elif cmd.startswith("/skills"):
            parts = cmd.split()
            _cmd_skills(parts[1:])

        elif cmd.startswith("/sessions"):
            parts = cmd.split()
            _cmd_sessions(parts[1:])

        elif cmd == "/status":
            _print_status()

        elif cmd == "/new":
            console.print("[dim]请直接输入你的需求[/dim]")

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

        elif cmd == "/retry":
            if _supervisor:
                _supervisor.retry_current_step()

        elif cmd == "/skip":
            if _supervisor:
                _supervisor.skip_current_step()

        elif cmd == "/edit":
            console.print("[dim]功能开发中 (Phase 6+)[/dim]")

        elif not cmd.startswith("/"):
            if _supervisor and _supervisor.state == SupervisorState.IDLE:
                try:
                    plan = _supervisor.submit(cmd)
                    _print_plan_confirmation(plan)
                except Exception as exc:
                    console.print(f"[red]错误: {exc}[/red]")
            else:
                console.print("[dim]当前有任务进行中，请先 /abort 后再提交新任务[/dim]")

        else:
            console.print(f"[red]未知命令: {cmd}[/red]")
            console.print("输入 /help 查看可用命令")


if __name__ == "__main__":
    main()
