"""测试 LLMPlanner：真实模型输出的结构化解析（不碰网络）。

全部使用假 complete() 函数注入，覆盖：
- T01: 正常 JSON 输出 → Plan 解析成功，字段正确
- T02: 带 ```json 围栏的输出 → 围栏剥除后解析成功
- T03: 非 JSON 文本 → PlanParseError
- T04: 缺少 steps 字段 → PlanParseError
- T05: steps 为空 → create_plan 工厂拒绝（ValueError）
- T06: step_id 重复 → create_plan 工厂拒绝（ValueError）
- T07: 步骤缺必填字段 → ValidationError
- T08: 步骤字段空白 → ValidationError
- T09: 模型返回非 PENDING 初始状态 → create_plan 工厂拒绝
- T10: complete 抛异常 → 原样传播，不被吞
- T11: prompt 包含 Goal/约束/仓库证据
- T12: 接口边界 —— LLMPlanner 只有 create_plan，无执行方法
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from codeteam.planning.planner import (
    LLMPlanner,
    PlanParseError,
    RepositoryContext,
    _build_planning_prompt,
    _strip_code_fences,
)
from codeteam.task.models import TaskSpec

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _task() -> TaskSpec:
    return TaskSpec(
        task_id="t-001",
        original_request="修复登录超时问题",
        goal="登录请求超时后能按策略重试而不是直接失败",
        constraints=("不能修改公开 API",),
        acceptance_criteria=("pytest tests/auth/test_timeout.py 返回 0",),
    )


def _ctx() -> RepositoryContext:
    return RepositoryContext(
        summary="任务: 修复登录超时 | 相关文件: 2 | 候选总数: 5",
        relevant_files=("src/auth/service.py", "src/http/client.py"),
        relevant_symbols=("AuthService",),
        instructions=("用 pytest 测试",),
        test_commands=("test: pytest",),
    )


def _good_json() -> str:
    return json.dumps(
        {
            "steps": [
                {
                    "step_id": "P1",
                    "title": "Trace timeout flow",
                    "description": "定位 timeout 配置与调用链",
                    "relevant_files": ["src/auth/service.py"],
                    "verification": None,
                },
                {
                    "step_id": "P2",
                    "title": "Apply fix",
                    "description": "修改 timeout/retry 逻辑",
                    "relevant_files": [],
                    "verification": "pytest tests/auth/test_timeout.py",
                },
            ]
        }
    )


# ===================================================================
# T01-T02: 正常解析
# ===================================================================

class TestLlamaPlannerParsing:
    """T01-T02: 正常 JSON 与围栏剥除。"""

    def test_parses_valid_json_output(self) -> None:
        """T01: 模型输出合法 JSON → 解析为有效 Plan。"""
        planner = LLMPlanner(complete=lambda prompt: _good_json())

        plan = planner.create_plan(task=_task(), repo_context=_ctx())

        assert len(plan.steps) == 2
        assert plan.task_id == "t-001"
        assert plan.version == 1
        assert plan.steps[0].step_id == "P1"
        assert plan.steps[0].status.value == "pending"
        assert plan.steps[0].relevant_files == ("src/auth/service.py",)
        assert plan.steps[0].verification is None
        assert plan.steps[1].verification == "pytest tests/auth/test_timeout.py"

    def test_strips_json_code_fences(self) -> None:
        """T02: 模型输出带 ```json 围栏 → 剥除后解析成功。"""
        fenced = "```json\n" + _good_json() + "\n```"
        planner = LLMPlanner(complete=lambda prompt: fenced)

        plan = planner.create_plan(task=_task(), repo_context=_ctx())

        assert len(plan.steps) == 2


# ===================================================================
# T03-T05: 解析失败
# ===================================================================

class TestLlamaPlannerParseFailures:
    """T03-T05: 坏输出必须显式失败，不被静默修补。"""

    def test_invalid_json_raises_plan_parse_error(self) -> None:
        """T03: 非 JSON 文本 → PlanParseError（带异常链）。"""
        planner = LLMPlanner(complete=lambda prompt: "这不是 JSON，是散文")

        with pytest.raises(PlanParseError):
            planner.create_plan(task=_task(), repo_context=_ctx())

    def test_missing_steps_field_raises(self) -> None:
        """T04: JSON 合法但缺 steps 字段 → PlanParseError。"""
        planner = LLMPlanner(complete=lambda prompt: '{"plan_id": "x"}')

        with pytest.raises(PlanParseError):
            planner.create_plan(task=_task(), repo_context=_ctx())

    def test_empty_steps_rejected_by_factory(self) -> None:
        """T05: steps 为空 → create_plan 工厂拒绝（ValueError）。

        验证 Runtime 不变量 len(plan.steps) >= 1：
        Planner 不校验，工厂校验。
        """
        planner = LLMPlanner(complete=lambda prompt: '{"steps": []}')

        with pytest.raises(ValueError):
            planner.create_plan(task=_task(), repo_context=_ctx())

    def test_duplicate_step_ids_rejected(self) -> None:
        """T06: step_id 重复 → create_plan 工厂拒绝。"""
        dup = json.dumps(
            {
                "steps": [
                    {"step_id": "P1", "title": "a", "description": "a"},
                    {"step_id": "P1", "title": "b", "description": "b"},
                ]
            }
        )
        planner = LLMPlanner(complete=lambda prompt: dup)

        with pytest.raises(ValueError):
            planner.create_plan(task=_task(), repo_context=_ctx())


# ===================================================================
# T07-T09: 字段校验
# ===================================================================

class TestLlamaPlannerFieldValidation:
    """T07-T09: 模型输出字段由 Pydantic 与工厂双层校验。"""

    def test_missing_required_field_raises_validation_error(self) -> None:
        """T07: 步骤缺 description → ValidationError。"""
        bad = json.dumps(
            {
                "steps": [
                    {"step_id": "P1", "title": "a"},
                ]
            }
        )
        planner = LLMPlanner(complete=lambda prompt: bad)

        with pytest.raises(ValidationError):
            planner.create_plan(task=_task(), repo_context=_ctx())

    def test_blank_field_raises_validation_error(self) -> None:
        """T08: 步骤 title 为空白 → ValidationError（strip 后为空）。"""
        bad = json.dumps(
            {
                "steps": [
                    {"step_id": "P1", "title": "   ", "description": "a"},
                ]
            }
        )
        planner = LLMPlanner(complete=lambda prompt: bad)

        with pytest.raises(ValidationError):
            planner.create_plan(task=_task(), repo_context=_ctx())

    def test_non_pending_initial_status_rejected(self) -> None:
        """T09: 模型返回 status=completed 的步骤 → 工厂拒绝。

        新建 Plan 的步骤必须全部 PENDING——模型不能
        在一开始就声称步骤已完成。
        """
        bad = json.dumps(
            {
                "steps": [
                    {
                        "step_id": "P1",
                        "title": "a",
                        "description": "a",
                        "status": "completed",
                    },
                ]
            }
        )
        planner = LLMPlanner(complete=lambda prompt: bad)

        with pytest.raises(ValueError):
            planner.create_plan(task=_task(), repo_context=_ctx())


# ===================================================================
# T10-T12: 错误传播 / Prompt / 接口边界
# ===================================================================

class TestLlamaPlannerPropagation:
    """T10-T12: 异常传播、Prompt 契约、接口边界。"""

    def test_complete_exception_propagates(self) -> None:
        """T10: complete 抛异常 → 原样传播，Planner 不吞。

        由 Orchestrator 总闸门统一转成 Task FAILED。
        """
        planner = LLMPlanner(
            complete=lambda prompt: (_ for _ in ()).throw(
                TimeoutError("llm timeout")
            )
        )

        with pytest.raises(TimeoutError):
            planner.create_plan(task=_task(), repo_context=_ctx())

    def test_prompt_contains_goal_constraints_and_evidence(self) -> None:
        """T11: 构造的 prompt 包含 Goal/约束/仓库证据/输出契约。"""
        prompt = _build_planning_prompt(_task(), _ctx())

        assert "登录请求超时后能按策略重试" in prompt          # Goal
        assert "不能修改公开 API" in prompt                    # Constraint
        assert "pytest tests/auth/test_timeout.py 返回 0" in prompt  # Acceptance
        assert "src/auth/service.py" in prompt                 # 仓库证据
        assert "src/http/client.py" in prompt                  # 仓库证据
        assert "AuthService" in prompt                         # 符号
        assert "只输出 JSON" in prompt                          # 输出契约
        assert '"steps"' in prompt                             # Schema 提示

    def test_strip_code_fences_boundary(self) -> None:
        """T12: 围栏剥除边界——无围栏原样、有围栏剥除、残缺围栏不丢内容。"""
        assert _strip_code_fences('{"a": 1}') == '{"a": 1}'

        assert _strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

        # 只有开头围栏、尾部无围栏：剥掉首行，内容保留
        assert _strip_code_fences('```json\n{"a": 1}') == '{"a": 1}'

    def test_planner_has_no_execution_methods(self) -> None:
        """T13: 接口边界——LLMPlanner 只有 create_plan。

        Planner 是 Decision Component，不是 Execution Engine。
        """
        planner = LLMPlanner(complete=lambda prompt: _good_json())

        assert hasattr(planner, "create_plan")
        assert not hasattr(planner, "apply_patch")
        assert not hasattr(planner, "run_tests")
        assert not hasattr(planner, "commit")
