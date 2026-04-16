"""Skill data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["Skill", "SkillInstance"]


@dataclass
class Skill:
    """A loadable skill that extends an agent's capabilities.

    A skill is a named bundle containing:
    - A system prompt template (with {placeholder} variables)
    - Optional init script (run once at load time)
    - Optional per-task script (run before each task)
    - Metadata (description, trigger keywords, version)

    Skills are installed under ~/.lustre/skills/ or bundled under
    the repo's skills/ directory.
    """

    name: str
    description: str
    prompt_template: str  # may contain {variables}

    # Optional scripts
    init_script: str | None = None   # runs once when skill is loaded
    task_script: str | None = None   # runs before each task

    # Metadata
    version: str = "0.0.0"
    author: str | None = None
    trigger_keywords: list[str] = field(default_factory=list)
    # e.g. ["fastapi", "flask"] — matched against task description

    # File origin (for display / debugging)
    source_path: Path | None = None

    # Runtime state
    variables: dict[str, str] = field(default_factory=dict)
    # resolved from environment or user config

    @property
    def resolved_prompt(self) -> str:
        """Render the prompt template with current variables."""
        if not self.variables:
            return self.prompt_template
        try:
            return self.prompt_template.format_map(self.variables)
        except KeyError as exc:
            return self.prompt_template  # fallback: return as-is

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "trigger_keywords": self.trigger_keywords,
            "source_path": str(self.source_path) if self.source_path else None,
            "has_init_script": self.init_script is not None,
            "has_task_script": self.task_script is not None,
            "variables": self.variables,
        }


@dataclass
class SkillInstance:
    """A skill that has been loaded and initialised for use.

    Created by SkillManager.load_skill().
    """

    skill: Skill
    active: bool = True

    # Results from running the init script (stdout captured)
    init_output: str | None = None

    @property
    def name(self) -> str:
        return self.skill.name

    @property
    def prompt(self) -> str:
        return self.skill.resolved_prompt

    def to_dict(self) -> dict[str, Any]:
        base = self.skill.to_dict()
        base["active"] = self.active
        base["init_output"] = self.init_output
        return base
