"""Interactive first-run setup wizard.

Guides the user through selecting a model provider, entering API keys,
and writing the initial ~/.lustre/config.yaml.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt, PromptType
from rich.text import Text

__all__ = ["run_wizard"]

console = Console()


# ---------------------------------------------------------------------------
# Available model providers
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "1": {
        "name": "Anthropic (Claude)",
        "key_env": "ANTHROPIC_API_KEY",
        "key_example": "sk-ant-...",
        "default_model": "claude-sonnet-4-6",
        "models": [
            ("claude-sonnet-4-6", "Claude Sonnet 4 (推荐)"),
            ("claude-opus-4-6", "Claude Opus 4 (更强)"),
            ("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
            ("claude-3-5-haiku-20241022", "Claude 3.5 Haiku (快速)"),
        ],
    },
    "2": {
        "name": "OpenAI (GPT-4o / o1)",
        "key_env": "OPENAI_API_KEY",
        "key_example": "sk-...",
        "default_model": "gpt-4o",
        "models": [
            ("gpt-4o", "GPT-4o (推荐)"),
            ("gpt-4o-mini", "GPT-4o Mini (快速/便宜)"),
            ("o1", "OpenAI o1 (推理)"),
            ("o3-mini", "OpenAI o3 Mini"),
        ],
    },
    "3": {
        "name": "MiniMax (MiniMax-Text-01)",
        "key_env": "MINIMAX_API_KEY",
        "key_example": "...",
        "default_model": "MiniMax-Text-01",
        "models": [
            ("MiniMax-Text-01", "MiniMax Text 01 (推荐)"),
        ],
    },
    "4": {
        "name": "自定义中转站 (OpenAI 兼容格式)",
        "key_env": "",
        "key_example": "",
        "default_model": "",
        "models": [],
    },
    "5": {
        "name": "本地模型 / Other (手动配置)",
        "key_env": "",
        "key_example": "",
        "default_model": "",
        "models": [],
    },
}


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

def run_wizard() -> dict:
    """Run the interactive first-run wizard.

    Returns the config dict to write to ~/.lustre/config.yaml.
    """
    _ensure_lustre_home()

    console.print()
    console.print(Panel(
        "[bold gold1]Lustre Agent 首次启动向导[/bold gold1]\n"
        "我将帮你配置 LLM 模型。完成后会写入 [dim]~/.lustre/config.yaml[/dim]。",
        border_style="gold1",
        expand=False,
    ))
    console.print()

    # Step 1: Choose provider
    console.print("[bold]步骤 1/4 — 选择模型提供商[/bold]")
    console.print()

    for num, prov in _PROVIDERS.items():
        key_display = (
            f"[dim]Key env: {prov['key_env']}[/dim]"
            if prov["key_env"]
            else "[dim]手动配置[/dim]"
        )
        console.print(f"  [cyan]{num}[/cyan]. {prov['name']}  {key_display}")

    console.print()
    choice = Prompt.ask(
        "请选择 [1-5]",
        default="1",
        choices=["1", "2", "3", "4", "5"],
        show_default=True,
    )
    prov = _PROVIDERS[choice]
    provider_name = prov["name"]

    console.print(f"[green]✓[/green] 已选择: {provider_name}")

    # Step 2: Enter API key (unless "other")
    api_key = ""
    custom_base_url = ""
    if choice == "4":
        console.print()
        console.print("[bold]步骤 2/4 — 配置自定义中转站[/bold]")
        console.print()
        custom_base_url = Prompt.ask("中转站 Base URL（如 https://api.example.com/v1）").strip()
        raw_key = getpass("API Key: ")
        api_key = raw_key.strip()
        console.print(f"[green]✓[/green] 中转站已配置")
    elif prov["key_env"]:
        console.print()
        console.print("[bold]步骤 2/4 — 输入 API Key[/bold]")
        console.print(f"  环境变量 [dim]{prov['key_env']}[/dim] 如果已设置则直接回车跳过")
        console.print()

        existing = os.environ.get(prov["key_env"], "")
        if existing:
            console.print(f"  [dim]检测到已有值: {existing[:8]}...[/dim]")

        raw_key = getpass(f"请输入 {prov['key_env']} (直接回车跳过): ")
        api_key = raw_key.strip()

        if not api_key and existing:
            api_key = existing

        if not api_key:
            console.print("[yellow]! 未提供 API Key，将使用环境变量（如果后续设置了的话）[/yellow]")
        else:
            console.print(f"[green]✓[/green] API Key 已记录")

    # Step 3: Choose model
    default_model = prov["default_model"]
    base_url = custom_base_url  # may be set by custom provider
    if prov["models"]:
        console.print()
        console.print("[bold]步骤 3/4 — 选择模型[/bold]")
        console.print()

        for i, (model_id, model_desc) in enumerate(prov["models"], 1):
            default_marker = " [dim](默认)[/dim]" if model_id == default_model else ""
            console.print(f"  [cyan]{i}[/cyan]. {model_desc}{default_marker}")

        console.print()
        model_choice = Prompt.ask(
            f"请选择 [1-{len(prov['models'])}]",
            default="1",
        )
        model_idx = max(1, min(int(model_choice), len(prov["models"]))) - 1
        model_name = prov["models"][model_idx][0]
        console.print(f"[green]✓[/green] 已选择: {model_name}")

        if choice == "3" and not base_url:
            base_url = "https://api.minimax.chat/v1"
            console.print(f"  [dim]Base URL: {base_url}[/dim]")
    else:
        console.print()
        console.print("[bold]步骤 3/4 — 输入模型名称[/bold]")
        if choice == "4":
            console.print(f"  [dim]中转站: {base_url}[/dim]")
        else:
            console.print("  请手动输入你要使用的模型名称（如 gpt-4o）")
        console.print()
        model_name = Prompt.ask("模型名称").strip()
        if not base_url:
            base_url = Prompt.ask("Base URL（可选，回车跳过）").strip()
        console.print(f"[green]✓[/green] 已记录: {model_name}")

    # Step 4: Review
    console.print()
    console.print("[bold]步骤 4/4 — 确认并保存[/bold]")
    console.print()

    # Build config dict
    if choice == "1":
        provider_key = "anthropic"
    elif choice == "2":
        provider_key = "openai"
    elif choice == "3":
        provider_key = "minimax"
    elif choice == "4":
        provider_key = "custom"
    else:
        provider_key = "openai"  # fallback

    cfg: dict = {
        "version": "1.0",
        "system": {"version": "0.9.0"},
        "model": {
            "provider": provider_key,
            "model": model_name,
            "api_key": api_key or (f"${{{prov['key_env']}}}" if prov["key_env"] else ""),
        },
        "agents": {
            "code": {
                "model_provider": provider_key,
                "model_name": model_name,
                "api_key": api_key or (f"${{{prov['key_env']}}}" if prov["key_env"] else ""),
            },
        },
        "tools": {
            "enabled": [
                "read_file",
                "write_file",
                "patch",
                "terminal",
                "search_files",
            ],
        },
        "message_bus": {"type": "memory"},
        "session": {"db_path": "~/.lustre/sessions.db"},
    }

    if base_url:
        cfg["model"]["base_url"] = base_url
        if "api_key" in cfg["model"] and cfg["model"]["api_key"] == f"${{{prov['key_env']}}}":
            pass  # keep env var ref
        cfg["agents"]["code"]["base_url"] = base_url

    # Show config preview
    import yaml
    preview = yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False)
    console.print(Panel(
        Text(preview, style="dim"),
        title="将写入的配置",
        border_style="dim",
    ))

    console.print()
    save = Confirm.ask("确认保存到 [dim]~/.lustre/config.yaml[/dim]", default=True)
    if not save:
        console.print("[yellow]已取消，程序将以默认配置启动（部分功能可能不可用）[/yellow]")
        return {}

    # Write config
    config_path = Path.home() / ".lustre" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(preview, encoding="utf-8")

    # Also write .env if we got an API key and it differs from env
    if api_key and prov["key_env"]:
        env_path = Path.home() / ".lustre" / ".env"
        existing_env = ""
        if env_path.exists():
            existing_env = env_path.read_text()
        # Only add if not already present
        if prov["key_env"] not in existing_env:
            with open(env_path, "a") as f:
                f.write(f"\n{prov['key_env']}={api_key}\n")

    console.print()
    console.print(Panel(
        "[green]✓ 配置已保存到 ~/.lustre/config.yaml[/green]\n"
        "后续可用 [cyan]/config edit[/cyan] 或 [cyan]lustre config[/cyan] 修改。",
        border_style="green",
        expand=False,
    ))

    return cfg


def _ensure_lustre_home() -> None:
    """Ensure ~/.lustre directory exists."""
    home = Path.home() / ".lustre"
    home.mkdir(parents=True, exist_ok=True)
