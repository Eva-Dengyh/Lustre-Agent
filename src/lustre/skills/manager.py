"""SkillManager — discovers, loads, and manages skills."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from lustre.skills.models import Skill, SkillInstance

__all__ = ["SkillManager"]


# ---------------------------------------------------------------------------
# Search paths for skills
# ---------------------------------------------------------------------------

def _default_skill_dirs() -> list[Path]:
    """Return skill search paths, in priority order.

    1. ~/.lustre/skills/  (user-installed, highest priority)
    2. <repo>/skills/      (bundled skills)
    """
    dirs = []

    home_skills = Path.home() / ".lustre" / "skills"
    dirs.append(home_skills)

    # Repo-level skills/ directory (relative to this file's location)
    repo_skills = Path(__file__).parent.parent.parent.parent / "skills"
    if repo_skills.exists():
        dirs.append(repo_skills)

    return dirs


# ---------------------------------------------------------------------------
# Skill discovery from a directory
# ---------------------------------------------------------------------------

def _discover_skill_dirs(dirs: list[Path]) -> dict[str, list[Path]]:
    """Find all skill directories under the given paths.

    Returns:
        {skill_name: [path1, path2]} — deduped by name, first path wins.
    """
    result: dict[str, list[Path]] = {}

    for base in dirs:
        if not base.exists():
            continue
        for item in sorted(base.iterdir()):
            if not item.is_dir():
                continue
            skill_name = item.name
            if skill_name.startswith(".") or skill_name.startswith("_"):
                continue
            if skill_name not in result:
                result[skill_name] = []
            result[skill_name].append(item)

    return result


def _load_skill_from_dir(path: Path) -> Skill:
    """Load a skill from a directory.

    Expected structure:
        skill_name/
        ├── SKILL.md          # required: name, description, prompt_template
        ├── init.py           # optional: init script
        └── task.py           # optional: per-task script
    """
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise ValueError(f"Skill {path.name!r} is missing SKILL.md")

    # Parse SKILL.md frontmatter
    text = skill_md.read_text(encoding="utf-8")
    skill = _parse_skill_md(path.name, text)
    skill.source_path = path

    # Load optional scripts
    init_py = path / "init.py"
    if init_py.exists():
        skill.init_script = init_py.read_text(encoding="utf-8")

    task_py = path / "task.py"
    if task_py.exists():
        skill.task_script = task_py.read_text(encoding="utf-8")

    return skill


def _parse_skill_md(name: str, text: str) -> Skill:
    """Parse YAML frontmatter + body from a SKILL.md file.

    Format:
        ---
        name: fastapi
        description: Expert in FastAPI web framework
        version: 1.0.0
        author: Eva
        trigger_keywords: [fastapi, api route]
        ---
        ## System Prompt
        You are a FastAPI expert...
    """
    import re
    import yaml

    # Extract YAML frontmatter
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        # No frontmatter — use name as description, entire body as template
        return Skill(name=name, description=text[:100], prompt_template=text)

    frontmatter_raw = match.group(1)
    body = text[match.end():]

    try:
        meta = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter in {name!r}: {exc}") from exc

    # Build prompt_template from body (everything after ---)
    prompt_template = body.strip()

    return Skill(
        name=meta.get("name", name),
        description=meta.get("description", ""),
        prompt_template=prompt_template or meta.get("prompt", ""),
        version=meta.get("version", "0.0.0"),
        author=meta.get("author"),
        trigger_keywords=meta.get("trigger_keywords", []),
    )


# ---------------------------------------------------------------------------
# SkillManager
# ---------------------------------------------------------------------------

class SkillManager:
    """Discovers and manages skills from multiple search paths.

    Usage:
        sm = SkillManager()
        sm.discover()  # scan all skill directories

        # List available skills
        for name in sm.list_skill_names():
            print(name, sm.get_skill(name).description)

        # Load a skill for use
        instance = sm.load_skill("fastapi")
        print(instance.prompt)  # resolved prompt

        # Check which skills match a task description
        matched = sm.match_skills("帮我写一个 FastAPI 接口")
        for si in matched:
            print(f"  → {si.name}")
    """

    def __init__(
        self,
        search_dirs: list[Path] | None = None,
    ) -> None:
        self._search_dirs = search_dirs or _default_skill_dirs()
        self._discovered: dict[str, Skill] = {}  # name → Skill (first found)
        self._loaded: dict[str, SkillInstance] = {}  # name → active instance
        self._init_scripts_ran: set[str] = set()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Scan all search directories and register skill metadata.

        For skills with the same name in multiple directories, the first
        one found (highest priority) wins.
        """
        self._discovered.clear()
        for name, paths in _discover_skill_dirs(self._search_dirs).items():
            if name not in self._discovered:
                try:
                    self._discovered[name] = _load_skill_from_dir(paths[0])
                except Exception as exc:
                    # Log but don't fail — other skills may be valid
                    import logging
                    logging.warning("Failed to load skill %r from %s: %s", name, paths[0], exc)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_skill_names(self) -> list[str]:
        """Return sorted list of all discovered skill names."""
        return sorted(self._discovered.keys())

    def get_skill(self, name: str) -> Skill | None:
        """Return the Skill metadata for a named skill (first found)."""
        return self._discovered.get(name)

    def is_loaded(self, name: str) -> bool:
        """Return True if the skill is currently loaded."""
        return name in self._loaded

    def get_loaded(self) -> list[SkillInstance]:
        """Return all active skill instances."""
        return list(self._loaded.values())

    # ------------------------------------------------------------------
    # Load / unload
    # ------------------------------------------------------------------

    def load_skill(
        self,
        name: str,
        variables: dict[str, str] | None = None,
        run_init: bool = True,
    ) -> SkillInstance | None:
        """Load a discovered skill by name.

        Runs the init script (if present and not yet run).
        Stores an active SkillInstance in self._loaded.
        """
        skill = self._discovered.get(name)
        if not skill:
            return None

        if name in self._loaded and not run_init:
            # Reuse existing instance
            return self._loaded[name]

        instance = SkillInstance(skill=skill)
        if variables:
            instance.skill.variables.update(variables)

        if run_init and skill.init_script and name not in self._init_scripts_ran:
            instance.init_output = self._run_init_script(skill.init_script, skill.name)
            self._init_scripts_ran.add(name)

        instance.active = True
        self._loaded[name] = instance
        return instance

    def unload_skill(self, name: str) -> None:
        """Remove a skill from the active set."""
        self._loaded.pop(name, None)

    def load_all(self) -> None:
        """Load all discovered skills."""
        for name in self._discovered:
            self.load_skill(name, run_init=False)

    # ------------------------------------------------------------------
    # Skill matching
    # ------------------------------------------------------------------

    def match_skills(self, task_description: str) -> list[SkillInstance]:
        """Return all loaded skills whose trigger_keywords match the task.

        Matching is case-insensitive substring.
        """
        loaded = self.get_loaded()
        if not loaded:
            return []

        matched: list[SkillInstance] = []
        desc_lower = task_description.lower()

        for instance in loaded:
            keywords = instance.skill.trigger_keywords
            if not keywords:
                matched.append(instance)
                continue
            # Any keyword matches → include
            if any(kw.lower() in desc_lower for kw in keywords):
                matched.append(instance)

        return matched

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_init_script(script: str, skill_name: str) -> str:
        """Execute a skill's init script in a subprocess.

        The script runs with the lustre package on sys.path.
        """
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as fh:
            fh.write(script)
            script_path = fh.name

        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=Path.cwd(),
            )
            output = (result.stdout + result.stderr).strip()
            return output or "(无输出)"
        except subprocess.TimeoutExpired:
            return "[超时] init 脚本超过 30 秒"
        except Exception as exc:  # noqa: BLE001
            return f"[错误] {exc}"
        finally:
            Path(script_path).unlink(missing_ok=True)
