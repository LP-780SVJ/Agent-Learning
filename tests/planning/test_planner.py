"""测试 Planner 接口与 Mock 层（codeteam/planning/planner.py）。

覆盖 day1.md 一百零五节验收：
- MockPlanner：注入 Plan 原样返回 / 注入 error 抛出 / 双缺省 RuntimeError / calls 审计
- FailingPlanner：总是抛出指定异常，calls 计数
- RepositoryContext：字段默认值与构造
- Planner Protocol：接口只声明 create_plan，MockPlanner 无需显式继承

（LLMPlanner 的解析层测试见同目录 test_llm_planner.py，不重复。）
"""

from __future__ import annotations

import pytest

from codeteam.planning.models import PlanStep, create_plan
from codeteam.planning.planner import (
    FailingPlanner,
    MockPlanner,
    Planner,
    RepositoryContext,
)
from codeteam.task.models import TaskSpec


def _task(task_id: str = "t-001") -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        original_request="修复登录超时",
        goal="修复登录超时",
    )


def _ctx() -> RepositoryContext:
    return RepositoryContext(summary="s")


def _plan(task_id: str = "t-001") -> object:
    return create_plan(
        plan_id=f"{task_id}-plan-v1",
        task_id=task_id,
        steps=(
            PlanStep(step_id="P1", title="t1", description="d1"),
            PlanStep(step_id="P2", title="t2", description="d2"),
        ),
    )


# ===================================================================
# MockPlanner
# ===================================================================

class TestMockPlanner:
    """MockPlanner 注入行为与审计。"""

    def test_returns_injected_plan_unchanged(self) -> None:
        """验收(Mock 层): 注入的 Plan 原样返回（同一对象）。"""
        plan = _plan()
        mock = MockPlanner(plan=plan)

        result = mock.create_plan(task=_task(), repo_context=_ctx())

        assert result is plan
        assert len(result.steps) == 2

    def test_injected_error_raised_on_every_call(self) -> None:
        """验收(Mock 层): 注入 error 时每次调用都抛出该异常。"""
        mock = MockPlanner(error=RuntimeError("model api down"))

        with pytest.raises(RuntimeError, match="model api down"):
            mock.create_plan(task=_task(), repo_context=_ctx())
        with pytest.raises(RuntimeError, match="model api down"):
            mock.create_plan(task=_task(), repo_context=_ctx())

    def test_neither_plan_nor_error_raises_runtime_error(self) -> None:
        """验收(Mock 层): 未注入 plan 也未注入 error → RuntimeError。"""
        mock = MockPlanner()

        with pytest.raises(RuntimeError):
            mock.create_plan(task=_task(), repo_context=_ctx())

    def test_calls_audit_records_task_id(self) -> None:
        """验收(Mock 层): calls 审计记录 task_id 与 original_request。"""
        plan = _plan()
        mock = MockPlanner(plan=plan)

        mock.create_plan(task=_task("t-a"), repo_context=_ctx())
        mock.create_plan(task=_task("t-b"), repo_context=_ctx())

        assert [c[0] for c in mock.calls] == ["t-a", "t-b"]
        assert mock.calls[0][1] == "修复登录超时"


# ===================================================================
# FailingPlanner
# ===================================================================

class TestFailingPlanner:
    """FailingPlanner 失败注入与计数。"""

    def test_always_raises_injected_error(self) -> None:
        """验收(Mock 层): 总是抛出指定异常。"""
        failing = FailingPlanner(error=TimeoutError("llm timeout"))

        with pytest.raises(TimeoutError):
            failing.create_plan(task=_task(), repo_context=_ctx())
        with pytest.raises(TimeoutError):
            failing.create_plan(task=_task(), repo_context=_ctx())

    def test_calls_counter_increments(self) -> None:
        """验收(Mock 层): calls 计数每次调用递增。"""
        failing = FailingPlanner(error=RuntimeError("x"))

        for _ in range(3):
            with pytest.raises(RuntimeError):
                failing.create_plan(task=_task(), repo_context=_ctx())

        assert failing.calls == 3


# ===================================================================
# RepositoryContext
# ===================================================================

class TestRepositoryContext:
    """RepositoryContext 构造与默认值。"""

    def test_defaults_are_empty_tuples(self) -> None:
        """验收(Mock 层): 除 summary 外字段默认空元组。"""
        ctx = RepositoryContext(summary="s")
        assert ctx.summary == "s"
        assert ctx.relevant_files == ()
        assert ctx.relevant_symbols == ()
        assert ctx.instructions == ()
        assert ctx.test_commands == ()

    def test_full_construction(self) -> None:
        """验收(Mock 层): 全字段构造正确。"""
        ctx = RepositoryContext(
            summary="auth 仓库",
            relevant_files=("src/auth/service.py",),
            relevant_symbols=("AuthService",),
            instructions=("用 pytest",),
            test_commands=("test: pytest",),
        )
        assert ctx.relevant_files == ("src/auth/service.py",)
        assert ctx.test_commands == ("test: pytest",)


# ===================================================================
# Planner Protocol
# ===================================================================

class TestPlannerProtocol:
    """Planner Protocol 的鸭子类型契约。"""

    def test_mock_planner_satisfies_protocol_without_inheritance(
        self,
    ) -> None:
        """验收(Planner 接口): MockPlanner 无需显式继承 Planner
        即满足接口（鸭子类型），且接口只声明 create_plan。"""
        mock = MockPlanner(plan=_plan())
        failing = FailingPlanner(error=RuntimeError("x"))

        # 鸭子类型：有 create_plan 方法即可
        assert hasattr(mock, "create_plan")
        assert hasattr(failing, "create_plan")

        # 没有显式继承 Planner
        assert Planner not in MockPlanner.__mro__
        assert Planner not in FailingPlanner.__mro__

        # 接口层面无执行方法（Planner 不是 Execution Engine）
        for planner in (mock, failing):
            assert not hasattr(planner, "apply_patch")
            assert not hasattr(planner, "run_tests")
            assert not hasattr(planner, "commit")

    def test_protocol_declares_only_create_plan(self) -> None:
        """验收(Planner 接口): Protocol 只声明 create_plan 一个方法。"""
        methods = [
            name
            for name in dir(Planner)
            if not name.startswith("_") and callable(getattr(Planner, name))
        ]
        assert methods == ["create_plan"]
