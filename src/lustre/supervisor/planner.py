"""Planner — breaks a user request into an ExecutionPlan.

Phase 3 uses simple keyword-based rules.  Phase 4 will replace this
with LLM-powered planning.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lustre.bus.message import TaskRequest
from lustre.supervisor.state_machine import ExecutionPlan, PlanStep

if TYPE_CHECKING:
    from lustre.bus.base import MessageBus


# ---------------------------------------------------------------------------
# Keyword patterns — Phase 3 fallback
# ---------------------------------------------------------------------------

# Agents that can handle a step
KNOWN_AGENTS = {"code", "test", "research", "review", "deploy"}

# Simple keyword → agent mapping
_KEYWORD_AGENT_MAP = {
    "research": ["调研", "对比", "调查", "分析", "搜索", "查找", "研究"],
    "code": ["写", "代码", "函数", "API", "实现", "创建", "修改", "重构", "build", "写一个"],
    "test": ["测试", "单元测试", "集成测试", "跑测试", "验证", "test"],
    "review": ["review", "审查", "review code"],
    "deploy": ["部署", "deploy", "上线", "发布"],
}


def _keyword_to_agent(description: str) -> str:
    """Map a step description to the most likely agent."""
    desc_lower = description.lower()
    for agent, keywords in _KEYWORD_AGENT_MAP.items():
        for kw in keywords:
            if kw in desc_lower:
                return agent
    return "code"  # default


def _build_plan_from_keywords(user_request: str, skip_first_confirmation: bool = False) -> ExecutionPlan:
    """Build a plan using simple keyword detection.

    This is a Phase 3 placeholder.  Phase 4 will replace this with LLM.
    """
    plan = ExecutionPlan(original_request=user_request)

    request_lower = user_request.lower()

    # Detect explicit mentions
    wants_research = any(kw in request_lower for kw in ["调研", "对比", "调查", "分析", "搜索", "研究", "fastapi", "flask"])
    wants_code = any(kw in request_lower for kw in ["写", "代码", "api", "实现", "创建", "修改", "fastapi", "flask", "函数", "python"])
    wants_test = any(kw in request_lower for kw in ["测试", "test", "单元测试", "跑测试"])

    # Build ordered step list
    if wants_research:
        plan.steps.append(PlanStep(
            description="调研技术方案（对比 FastAPI / Flask）",
            agent_name="research",
        ))
        plan.confirmation_points.append(plan.steps[-1].step_id)

    if wants_code:
        # Extract what to build from the request
        code_description = _extract_code_target(user_request)
        plan.steps.append(PlanStep(
            description=f"编写代码：{code_description}",
            agent_name="code",
        ))

    if wants_test and wants_code:
        plan.steps.append(PlanStep(
            description="编写并运行测试",
            agent_name="test",
        ))

    # Default fallback if nothing detected
    if not plan.steps:
        plan.steps.append(PlanStep(
            description=f"处理请求：{user_request}",
            agent_name="code",
        ))

    # Set agent assignments
    for step in plan.steps:
        plan.agent_assignments[step.agent_name] = step.agent_name

    return plan


def _extract_code_target(user_request: str) -> str:
    """Extract what code to write from the user request."""
    # Try to find "X 和 Y" or "X vs Y" patterns
    if "和" in user_request:
        parts = user_request.split("和")
        return parts[-1].strip().rstrip("，").rstrip(",")
    if " vs " in user_request or "VS" in user_request:
        parts = re.split(r"\s+vs\s+|\s+VS\s+", user_request)
        return parts[-1].strip()
    if "或者" in user_request:
        parts = user_request.split("或者")
        return parts[-1].strip()
    # Fallback: return the whole request
    return user_request


# ---------------------------------------------------------------------------
# Planner class
# ---------------------------------------------------------------------------

class Planner:
    """Breaks a user request into an ExecutionPlan.

    Phase 3: keyword-based rules (this module).
    Phase 4: LLM-powered planning (PlannerLLM subclass).
    """

    def __init__(self, bus: MessageBus | None = None) -> None:
        self.bus = bus

    def plan(self, user_request: str) -> ExecutionPlan:
        """Create an execution plan for the given user request.

        In Phase 3 this uses keyword-based rules.
        In Phase 4 it will call the LLM.
        """
        return _build_plan_from_keywords(user_request)

    def create_task_request(
        self,
        plan: ExecutionPlan,
        step: PlanStep,
    ) -> TaskRequest:
        """Create a TaskRequest for a single plan step."""
        return TaskRequest(
            task_id=step.step_id,
            description=step.description,
            context={
                "plan_id": plan.plan_id,
                "original_request": plan.original_request,
                "all_steps": [s.to_dict() for s in plan.steps],
            },
            skills_requested=[],  # populated in Phase 6
            confirmation_needed=step.step_id in plan.confirmation_points,
            confirmation_prompt=f"步骤「{step.description}」已完成，确认继续？" if step.step_id in plan.confirmation_points else None,
        )
