"""Skill system — loadable prompt templates that extend agent capabilities."""

from lustre.skills.models import Skill, SkillInstance
from lustre.skills.manager import SkillManager

__all__ = ["Skill", "SkillInstance", "SkillManager"]
