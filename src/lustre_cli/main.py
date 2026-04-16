"""lustre_cli — Command-line tool for Lustre Agent.

Subcommands:
    lustre init                    — Initialise ~/.lustre directory
    lustre skills install <name>  — Install a Skill from registry or URL
    lustre skills list            — List available skills in registry
    lustre config                 — Open config.yaml in editor
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

__all__ = ["main"]
__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LUSTRE_HOME = Path.home() / ".lustre"
DEFAULT_CONFIG = LUSTRE_HOME / "config.yaml"


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    """Create ~/.lustre directory with default config."""
    if LUSTRE_HOME.exists():
        print(f"[yellow]~/.lustre already exists[/yellow]")
        if not args.force:
            print("  Use --force to overwrite")
            return 1

    LUSTRE_HOME.mkdir(parents=True, exist_ok=True)
    (LUSTRE_HOME / "skills").mkdir(exist_ok=True)

    # Create default config
    if not DEFAULT_CONFIG.exists() or args.force:
        _write_default_config()
        print(f"[green]✓[/green] Created {DEFAULT_CONFIG}")
    else:
        print(f"[dim]Keeping existing config[/dim]")

    # Create skills dir
    skills_dir = LUSTRE_HOME / "skills"
    print(f"[green]✓[/green] Directory: {skills_dir}")

    print("\n[bold green]初始化完成！[/bold green]")
    print(f"  配置文件: {DEFAULT_CONFIG}")
    print(f"  Skills 目录: {skills_dir}")
    print("\n运行: python -m lustre")
    return 0


def _write_default_config() -> None:
    content = """# Lustre Agent 配置文件
# ~ 表示用户目录，配置变更后重启 CLI 生效

version: "1.0"

# LLM 配置
model:
  provider: anthropic          # anthropic | openai
  model: claude-sonnet-4-6     # 模型名称
  api_key: ${ANTHROPIC_API_KEY}  # 从环境变量读取

# Agent 配置
agents:
  code:
    model_provider: anthropic
    model_name: claude-sonnet-4-6

# 工具配置
tools:
  enabled:
    - read_file
    - write_file
    - patch
    - terminal
    - search_files

# 消息总线
message_bus:
  type: memory   # memory | redis (future)

# Session 配置
session:
  db_path: ~/.lustre/sessions.db
"""
    DEFAULT_CONFIG.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Skills commands
# ---------------------------------------------------------------------------

SKILL_REGISTRY = {
    "python-expert": {
        "description": "Python 专家 — PEP 8 / 类型提示 / Docstring / 测试规范",
        "url": None,  # bundled
    },
    "fastapi-expert": {
        "description": "FastAPI 专家 — 路由 / Pydantic / 依赖注入 / OpenAPI",
        "url": None,  # bundled
    },
}


def cmd_skills_list(args: argparse.Namespace) -> int:
    print("\n[bold]Lustre Skill 注册表[/bold]\n")
    for name, info in SKILL_REGISTRY.items():
        print(f"  [cyan]{name}[/cyan]")
        print(f"    {info['description']}")
        print()
    print(f"共 {len(SKILL_REGISTRY)} 个 Skill")
    return 0


def cmd_skills_install(args: argparse.Namespace) -> int:
    name = args.name
    target_dir = LUSTRE_HOME / "skills" / name

    if SKILL_REGISTRY.get(name, {}).get("url") is None:
        # Bundled skill — copy from repo
        repo_skills = Path(__file__).parent.parent.parent / "skills" / name
        if repo_skills.exists():
            if target_dir.exists() and not args.force:
                print(f"[yellow]Skill {name} 已安装，use --force 覆盖[/yellow]")
                return 1
            shutil.copytree(repo_skills, target_dir, dirs_exist_ok=True)
            print(f"[green]✓[/green] Installed {name} (bundled)")
            return 0
        else:
            print(f"[red]✗[/red] Skill {name} not found (not bundled)")
            return 1

    url = SKILL_REGISTRY[name]["url"]
    # Download from URL
    try:
        print(f"[dim]Downloading {name} from {url}...[/dim]")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "SKILL.md").write_bytes(content)
        print(f"[green]✓[/green] Installed {name} from {url}")
        return 0
    except Exception as exc:
        print(f"[red]✗[/red] Download failed: {exc}")
        return 1


# ---------------------------------------------------------------------------
# Config command
# ---------------------------------------------------------------------------

def cmd_config(args: argparse.Namespace) -> int:
    """Open config.yaml in $EDITOR."""
    if not DEFAULT_CONFIG.exists():
        print(f"[yellow]Config not found at {DEFAULT_CONFIG}, creating default...[/yellow]")
        _write_default_config()

    editor = os.environ.get("EDITOR", "vi")
    print(f"[dim]Opening {DEFAULT_CONFIG} with {editor}[/dim]...")
    try:
        subprocess.run([editor, str(DEFAULT_CONFIG)], check=True)
    except subprocess.CalledProcessError:
        return 1
    except FileNotFoundError:
        print(f"[red]$EDITOR ({editor}) not found. Set EDITOR env var.[/red]")
        print(f"\nConfig location: {DEFAULT_CONFIG}")
        return 1
    return 0


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lustre",
        description="Lustre Agent — Multi-Agent CLI Assistant",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    init_parser = sub.add_parser("init", help="Initialise ~/.lustre directory")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    # skills
    skills_parser = sub.add_parser("skills", help="Manage Skills")
    skills_sub = skills_parser.add_subparsers(dest="subcommand", required=True)

    skills_list_parser = skills_sub.add_parser("list", help="List available Skills")
    skills_install_parser = skills_sub.add_parser(
        "install", help="Install a Skill (bundled or from URL)"
    )
    skills_install_parser.add_argument("name", help="Skill name (e.g. fastapi-expert)")
    skills_install_parser.add_argument("--force", action="store_true", help="Overwrite existing")

    # config
    config_parser = sub.add_parser("config", help="Open config.yaml in $EDITOR")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "skills":
        if args.subcommand == "list":
            return cmd_skills_list(args)
        elif args.subcommand == "install":
            return cmd_skills_install(args)
    elif args.command == "config":
        return cmd_config(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
