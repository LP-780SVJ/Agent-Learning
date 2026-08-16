"""测试 TaskSpec 与 Plan 数据模型。

覆盖 day1.md 一百零五节验收：
- TaskSpec 构造 / 空输入拒绝 / strip / 默认值 / goal 初值 / JSON 往返
- PlanStep 校验与状态转移（Valid/Invalid Step Transition）
- Plan.is_complete（Plan Complete）/ has_failed_step（Plan Failure）
- create_plan 不变量（Plan 至少一个 Step / ID 唯一 / 初始 PENDING）
- validate_plan / replan（Replan: version+1、task_id 不变、旧 Plan 不被修改）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeteam.planning.models import (
    InvalidStepTransitionError,
    Plan,
    PlanStep,
    PlanStepStatus,
    create_plan,
    replan,
    validate_plan,
)
from codeteam.task.models import TaskSpec, create_task_spec


def _step(step_id: str, **kwargs) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        title=f"{step_id} title",
        description=f"{step_id} description",
        **kwargs,
    )


# ===================================================================
# TaskSpec
# ===================================================================

class TestTaskSpec:
    """TaskSpec 构造、校验与序列化。"""

    def test_valid_construction(self) -> None:
        """验收(TaskSpec): 合法构造，字段正确。"""
        spec = TaskSpec(
            task_id="t-001",
            original_request="修复登录超时",
            goal="登录超时自动重试",
            constraints=("不能修改公开 API",),
            acceptance_criteria=("pytest 返回 0",),
        )
        assert spec.task_id == "t-001"
        assert spec.original_request == "修复登录超时"
        assert spec.constraints == ("不能修改公开 API",)
        assert spec.acceptance_criteria == ("pytest 返回 0",)

    @pytest.mark.parametrize("field", ["task_id", "original_request", "goal"])
    @pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
    def test_blank_field_rejected(self, field: str, bad: str) -> None:
        """验收(TaskSpec 空输入拒绝): 空/纯空白字段 → ValidationError。"""
        kwargs = {
            "task_id": "t",
            "original_request": "req",
            "goal": "goal",
            field: bad,
        }
        with pytest.raises(ValidationError):
            TaskSpec(**kwargs)

    def test_strips_leading_trailing_whitespace(self) -> None:
        """验收(TaskSpec strip): 首尾空白自动去掉。"""
        spec = TaskSpec(
            task_id="  t-001  ",
            original_request="  修复bug  ",
            goal="\t登录重试\n",
        )
        assert spec.task_id == "t-001"
        assert spec.original_request == "修复bug"
        assert spec.goal == "登录重试"

    def test_constraints_and_acceptance_default_empty(self) -> None:
        """验收(TaskSpec 默认值): constraints/acceptance 默认空元组。"""
        spec = TaskSpec(
            task_id="t", original_request="r", goal="g"
        )
        assert spec.constraints == ()
        assert spec.acceptance_criteria == ()

    def test_create_task_spec_goal_equals_original_request(self) -> None:
        """验收(TaskSpec): create_task_spec 后 goal == original_request。"""
        spec = create_task_spec(
            task_id="t-002", original_request="修复登录超时问题"
        )
        assert spec.goal == spec.original_request
        assert spec.constraints == ()
        assert spec.acceptance_criteria == ()

    def test_json_round_trip(self) -> None:
        """验收(TaskSpec 序列化): model_dump_json 往返一致。"""
        spec = TaskSpec(
            task_id="t-003",
            original_request="修复登录超时",
            goal="登录超时自动重试",
            constraints=("不能修改公开 API",),
            acceptance_criteria=("pytest 返回 0",),
        )
        restored = TaskSpec.model_validate_json(spec.model_dump_json())
        assert restored == spec


# ===================================================================
# PlanStep
# ===================================================================

class TestPlanStep:
    """PlanStep 校验与状态转移。"""

    @pytest.mark.parametrize("field", ["step_id", "title", "description"])
    @pytest.mark.parametrize("bad", ["", "   "])
    def test_blank_field_rejected(self, field: str, bad: str) -> None:
        """验收(PlanStep 校验): 空/空白必填字段 → ValidationError。"""
        kwargs = {"step_id": "P1", "title": "t", "description": "d", field: bad}
        with pytest.raises(ValidationError):
            PlanStep(**kwargs)

    def test_defaults(self) -> None:
        """验收(PlanStep 默认值): relevant_files 默认空元组、
        verification 允许 None。"""
        step = PlanStep(step_id="P1", title="t", description="d")
        assert step.relevant_files == ()
        assert step.verification is None
        assert step.status == PlanStepStatus.PENDING

    def test_valid_transition_chain(self) -> None:
        """验收(Valid Step Transition): PENDING→RUNNING→COMPLETED 成功。"""
        step = _step("P1")
        step.transition_to(PlanStepStatus.RUNNING)
        step.transition_to(PlanStepStatus.COMPLETED)
        assert step.status == PlanStepStatus.COMPLETED

    def test_pending_direct_to_completed_rejected(self) -> None:
        """验收(Invalid Step Transition): PENDING→COMPLETED 直跳拒绝。"""
        step = _step("P1")
        with pytest.raises(InvalidStepTransitionError):
            step.transition_to(PlanStepStatus.COMPLETED)

    @pytest.mark.parametrize(
        "target", [PlanStepStatus.SKIPPED, PlanStepStatus.FAILED]
    )
    def test_pending_to_skipped_or_failed_legal(
        self, target: PlanStepStatus
    ) -> None:
        """验收(Valid Step Transition): PENDING→SKIPPED / FAILED 合法。"""
        step = _step("P1")
        step.transition_to(target)
        assert step.status == target

    @pytest.mark.parametrize(
        "target", [PlanStepStatus.COMPLETED, PlanStepStatus.FAILED,
                   PlanStepStatus.SKIPPED]
    )
    def test_terminal_states_cannot_transition(
        self, target: PlanStepStatus
    ) -> None:
        """验收(Terminal State): COMPLETED/FAILED/SKIPPED 均不可再转移。"""
        step = _step("P1")
        # 先合法走到 target
        if target == PlanStepStatus.COMPLETED:
            step.transition_to(PlanStepStatus.RUNNING)
            step.transition_to(PlanStepStatus.COMPLETED)
        else:
            step.transition_to(target)

        with pytest.raises(InvalidStepTransitionError):
            step.transition_to(PlanStepStatus.RUNNING)

    def test_failed_transition_does_not_change_status(self) -> None:
        """验收(Invalid Step Transition): 失败转移不改变 status。"""
        step = _step("P1")
        with pytest.raises(InvalidStepTransitionError):
            step.transition_to(PlanStepStatus.COMPLETED)
        assert step.status == PlanStepStatus.PENDING


# ===================================================================
# Plan 整体状态
# ===================================================================

class TestPlanState:
    """Plan.is_complete / has_failed_step。"""

    def test_is_complete_all_completed(self) -> None:
        """验收(Plan Complete): 全部 COMPLETED → True。"""
        plan = create_plan(
            plan_id="p", task_id="t",
            steps=(_step("P1"), _step("P2")),
        )
        for s in plan.steps:
            s.transition_to(PlanStepStatus.RUNNING)
            s.transition_to(PlanStepStatus.COMPLETED)
        assert plan.is_complete is True

    def test_is_complete_with_skipped(self) -> None:
        """验收(Plan Complete): 含 SKIPPED 步骤仍视为完成。"""
        plan = create_plan(
            plan_id="p", task_id="t",
            steps=(_step("P1"), _step("P2")),
        )
        plan.steps[0].transition_to(PlanStepStatus.RUNNING)
        plan.steps[0].transition_to(PlanStepStatus.COMPLETED)
        plan.steps[1].transition_to(PlanStepStatus.SKIPPED)
        assert plan.is_complete is True

    @pytest.mark.parametrize(
        "target", [PlanStepStatus.RUNNING, PlanStepStatus.FAILED]
    )
    def test_is_complete_false_when_not_done(
        self, target: PlanStepStatus
    ) -> None:
        """验收(Plan Complete): 存在 RUNNING/FAILED（或 PENDING）→ False。"""
        plan = create_plan(
            plan_id="p", task_id="t",
            steps=(_step("P1"), _step("P2")),
        )
        plan.steps[0].transition_to(PlanStepStatus.RUNNING)
        plan.steps[0].transition_to(PlanStepStatus.COMPLETED)
        if target == PlanStepStatus.RUNNING:
            plan.steps[1].transition_to(PlanStepStatus.RUNNING)
        else:
            plan.steps[1].transition_to(PlanStepStatus.FAILED)
        assert plan.is_complete is False

    def test_is_complete_false_with_pending(self) -> None:
        """验收(Plan Complete): 存在 PENDING → False。"""
        plan = create_plan(
            plan_id="p", task_id="t", steps=(_step("P1"),)
        )
        assert plan.is_complete is False

    def test_has_failed_step(self) -> None:
        """验收(Plan Failure): 存在 FAILED 步骤 → True。"""
        plan = create_plan(
            plan_id="p", task_id="t",
            steps=(_step("P1"), _step("P2")),
        )
        assert plan.has_failed_step is False
        plan.steps[1].transition_to(PlanStepStatus.FAILED)
        assert plan.has_failed_step is True
        # FAILED 时 is_complete 必然 False
        assert plan.is_complete is False


# ===================================================================
# create_plan / validate_plan / replan
# ===================================================================

class TestPlanFactories:
    """create_plan 不变量、validate_plan、replan。"""

    def test_create_plan_valid(self) -> None:
        """验收(Plan 至少一个 Step): 合法输入通过，
        version 默认 1、steps 全 PENDING。"""
        plan = create_plan(
            plan_id="p-001", task_id="t-001",
            steps=(_step("P1"), _step("P2")),
        )
        assert plan.version == 1
        assert len(plan.steps) == 2
        assert all(
            s.status == PlanStepStatus.PENDING for s in plan.steps
        )

    def test_create_plan_empty_steps_rejected(self) -> None:
        """验收(Plan 至少一个 Step): 空 steps → ValueError。"""
        with pytest.raises(ValueError):
            create_plan(plan_id="p", task_id="t", steps=())

    def test_create_plan_duplicate_ids_rejected(self) -> None:
        """验收(Plan 至少一个 Step/ID 唯一): 重复 step_id → ValueError。"""
        with pytest.raises(ValueError):
            create_plan(
                plan_id="p", task_id="t",
                steps=(_step("P1"), _step("P1")),
            )

    def test_create_plan_non_pending_rejected(self) -> None:
        """验收(初始状态合法): 非 PENDING 初始状态 → ValueError。"""
        running = _step("P1")
        running.transition_to(PlanStepStatus.RUNNING)
        with pytest.raises(ValueError):
            create_plan(plan_id="p", task_id="t", steps=(running,))

    def test_validate_plan_empty_and_duplicate(self) -> None:
        """验收(Plan 校验): 空 steps / 重复 ID 返回问题列表。"""
        empty = Plan(plan_id="p", task_id="t", steps=())
        problems = validate_plan(empty)
        assert problems  # 非空

        dup = Plan(
            plan_id="p", task_id="t",
            steps=(_step("P1"), _step("P1")),
        )
        assert any("重复" in p for p in validate_plan(dup))

    def test_validate_plan_valid_returns_empty(self) -> None:
        """验收(Plan 校验): 合法 Plan 返回空列表。"""
        plan = create_plan(
            plan_id="p", task_id="t", steps=(_step("P1"),)
        )
        assert validate_plan(plan) == []

    def test_replan_version_increments(self) -> None:
        """验收(Replan): version == 旧 version + 1、task_id 不变。"""
        v1 = create_plan(
            plan_id="p-001", task_id="t-001",
            steps=(_step("P1"), _step("P2")),
        )
        v2 = replan(existing=v1, new_steps=(_step("P1"), _step("P3")))

        assert v2.version == v1.version + 1 == 2
        assert v2.task_id == v1.task_id
        assert all(s.status == PlanStepStatus.PENDING for s in v2.steps)

    def test_replan_does_not_mutate_old_plan(self) -> None:
        """验收(Replan): 旧 Plan 对象不被修改（含 steps 状态）。"""
        v1 = create_plan(
            plan_id="p-001", task_id="t-001",
            steps=(_step("P1"), _step("P2")),
        )
        v1.steps[0].transition_to(PlanStepStatus.RUNNING)

        v2 = replan(existing=v1, new_steps=(_step("P1"), _step("P3")))

        # 旧 Plan 保持原样：v1 的 P1 仍在 RUNNING
        assert v1.version == 1
        assert v1.steps[0].status == PlanStepStatus.RUNNING
        # 新 Plan 独立：v2 的 P1 是全新的 PENDING
        assert v2.steps[0].status == PlanStepStatus.PENDING
        assert v2.steps[0] is not v1.steps[0]

    def test_replan_invalid_new_steps_rejected(self) -> None:
        """验收(Replan): 新 steps 非法（空）→ ValueError。"""
        v1 = create_plan(
            plan_id="p-001", task_id="t-001", steps=(_step("P1"),)
        )
        with pytest.raises(ValueError):
            replan(existing=v1, new_steps=())


# ===================================================================
# F1 回归：PlanStep 类型守卫
# ===================================================================

class TestPlanStepTypeGuard:
    """F1 回归: PlanStep.transition_to 拒绝非枚举输入。"""

    @pytest.mark.parametrize(
        "bad",
        ["running", "completed", None, 1],
        ids=["str-running", "str-completed", "none", "int"],
    )
    def test_non_enum_rejected_and_status_unchanged(self, bad) -> None:
        """验收(F1): 非法类型全部拒绝，status 不变。"""
        step = _step("P1")

        with pytest.raises(InvalidStepTransitionError):
            step.transition_to(bad)

        assert step.status == PlanStepStatus.PENDING

    def test_legal_enum_transition_still_works(self) -> None:
        """验收(F1 不破坏合法行为): PENDING→RUNNING 仍合法。"""
        step = _step("P1")
        step.transition_to(PlanStepStatus.RUNNING)
        assert step.status == PlanStepStatus.RUNNING
