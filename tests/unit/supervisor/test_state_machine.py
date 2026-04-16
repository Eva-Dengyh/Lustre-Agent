"""Unit tests for the Supervisor state machine."""

from __future__ import annotations

import pytest

from lustre.supervisor.planner import Planner
from lustre.supervisor.state_machine import (
    ExecutionPlan,
    PlanStep,
    SupervisorState,
    SupervisorStateError,
    SupervisorStateMachine,
    TaskContext,
)


# ---------------------------------------------------------------------------
# SupervisorStateMachine — valid transitions
# ---------------------------------------------------------------------------

def test_initial_state_is_idle() -> None:
    sm = SupervisorStateMachine()
    assert sm.state == SupervisorState.IDLE
    assert sm.is_idle
    assert not sm.is_active


def test_submit_task_idle_to_planning() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("write a function")
    assert sm.state == SupervisorState.PLANNING
    assert not sm.is_idle


def test_submit_task_from_planning_raises() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("first task")
    with pytest.raises(SupervisorStateError):
        sm.submit_task("second task")


def test_set_plan_planning_to_awaiting() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    assert sm.state == SupervisorState.AWAITING_CONFIRMATION


def test_confirm_plan_awaiting_to_executing() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    sm.confirm_plan()
    assert sm.state == SupervisorState.EXECUTING


def test_finish_executing_to_done() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    sm.confirm_plan()
    sm.finish()
    assert sm.state == SupervisorState.DONE


def test_abort_from_executing() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    sm.confirm_plan()
    sm.abort()
    assert sm.state == SupervisorState.ABORTED


def test_reset_done_to_idle() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    sm.finish()
    sm.reset()
    assert sm.state == SupervisorState.IDLE


def test_reset_aborted_to_idle() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    sm.abort()
    sm.reset()
    assert sm.state == SupervisorState.IDLE


def test_request_confirmation_executing_to_awaiting() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    sm.confirm_plan()
    sm.request_confirmation()
    assert sm.state == SupervisorState.AWAITING_CONFIRMATION


def test_state_history_recorded() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    sm.confirm_plan()
    history = sm.state_history()
    assert SupervisorState.PLANNING in history
    assert SupervisorState.AWAITING_CONFIRMATION in history
    # confirm_plan does NOT append EXECUTING to history (only transitions record the _previous_ state)
    assert SupervisorState.EXECUTING not in history


def test_reset_from_executing_raises() -> None:
    sm = SupervisorStateMachine()
    sm.submit_task("hello")
    plan = ExecutionPlan(original_request="hello")
    sm.set_plan(plan)
    sm.confirm_plan()  # → EXECUTING
    with pytest.raises(SupervisorStateError):
        sm.reset()  # reset only allowed from DONE/ABORTED


def test_abort_from_idle_raises() -> None:
    sm = SupervisorStateMachine()
    with pytest.raises(SupervisorStateError):
        sm.abort()


def test_finish_from_idle_raises() -> None:
    sm = SupervisorStateMachine()
    with pytest.raises(SupervisorStateError):
        sm.finish()


def test_is_active() -> None:
    sm = SupervisorStateMachine()
    assert not sm.is_active
    sm.submit_task("hello")
    assert sm.is_active
    sm.finish()
    assert not sm.is_active


# ---------------------------------------------------------------------------
# ExecutionPlan
# ---------------------------------------------------------------------------

def test_plan_current_step() -> None:
    plan = ExecutionPlan(original_request="test")
    plan.steps = [
        PlanStep(description="step 1", agent_name="code"),
        PlanStep(description="step 2", agent_name="test"),
    ]
    plan.current_step_index = 0
    assert plan.current_step() == plan.steps[0]
    plan.current_step_index = 1
    assert plan.current_step() == plan.steps[1]


def test_plan_advance_skips_completed() -> None:
    plan = ExecutionPlan(original_request="test")
    plan.steps = [
        PlanStep(description="s1", agent_name="code", status="completed"),
        PlanStep(description="s2", agent_name="test"),
    ]
    plan.current_step_index = 0
    plan.advance()
    assert plan.current_step_index == 1
    assert plan.current_step() == plan.steps[1]


def test_plan_advance_at_end_returns_none() -> None:
    plan = ExecutionPlan(original_request="test")
    plan.steps = [
        PlanStep(description="s1", agent_name="code", status="completed"),
    ]
    plan.current_step_index = 0
    plan.advance()
    assert plan.current_step() is None


def test_plan_to_dict() -> None:
    plan = ExecutionPlan(original_request="hello")
    step = PlanStep(description="s1", agent_name="code")
    plan.steps.append(step)
    d = plan.to_dict()
    assert d["original_request"] == "hello"
    assert len(d["steps"]) == 1
    assert d["steps"][0]["description"] == "s1"


# ---------------------------------------------------------------------------
# TaskContext
# ---------------------------------------------------------------------------

def test_task_context_to_dict() -> None:
    ctx = TaskContext(user_request="build an API")
    d = ctx.to_dict()
    assert d["user_request"] == "build an API"
    assert d["plan"] is None
    assert d["state"] == SupervisorState.IDLE.value


def test_task_context_to_dict_with_plan() -> None:
    plan = ExecutionPlan(original_request="hello")
    ctx = TaskContext(user_request="hello", plan=plan)
    d = ctx.to_dict()
    assert d["plan"]["original_request"] == "hello"


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def test_planner_detects_research_and_code() -> None:
    planner = Planner()
    # "FastAPI" and "Flask" trigger research keywords; "写" triggers code
    # No test keywords present, so test step is NOT added
    plan = planner.plan("调研 FastAPI 和 Flask，然后写一个 hello world API")
    assert len(plan.steps) == 2
    assert plan.steps[0].agent_name == "research"
    assert plan.steps[1].agent_name == "code"
    # research step should have a confirmation gate
    assert plan.steps[0].step_id in plan.confirmation_points


def test_planner_detects_code_only() -> None:
    planner = Planner()
    # Use a framework name that doesn't trigger research
    plan = planner.plan("写一个 hello world API")
    assert len(plan.steps) == 1
    assert plan.steps[0].agent_name == "code"


def test_planner_detects_research_code_test() -> None:
    planner = Planner()
    plan = planner.plan("调研 Redis，然后写一个缓存模块，并写测试")
    assert len(plan.steps) == 3


def test_planner_creates_task_request() -> None:
    planner = Planner()
    plan = planner.plan("写一个函数")
    step = plan.steps[0]
    req = planner.create_task_request(plan, step)
    assert req.task_id == step.step_id
    assert req.description == step.description
