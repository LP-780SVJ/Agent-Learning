"""测试 SingleAgentOrchestrator 集成与状态驱动。

覆盖 day1.md 一百零五节验收：
- 普通任务 → READY（管线走通，不执行 P1）
- 空任务早失败（进 LLM 前失败，不浪费 Token）
- Planner 异常 → FAILED（绝不卡死）
- 非法 Plan → FAILED（Plan Validation 闸门）
- 事件序列完整断言（Observability）
- READY 零副作用（磁盘零变更）

测试隔离：真实 Context Engine 的用例使用 fixture 拷贝（conftest.repo_copy），
其余用例注入假 Inspector——真实临时环境优先，只 Mock 外部依赖。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from codeteam.agent.inspection import RepositoryInspector
from codeteam.agent.orchestrator import SingleAgentOrchestrator
from codeteam.application.build_context import ContextApplicationService
from codeteam.events import AgentEventType
from codeteam.planning.models import Plan, PlanStep, create_plan
from codeteam.planning.planner import (
    FailingPlanner,
    MockPlanner,
    RepositoryContext,
)
from codeteam.task.state import TaskStatus

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _plan() -> Plan:
    return create_plan(
        plan_id="t-001-plan-v1",
        task_id="t-001",
        steps=(
            PlanStep(step_id="P1", title="Inspect", description="d1"),
            PlanStep(step_id="P2", title="Fix", description="d2"),
        ),
    )


class _FakeInspector:
    """假 Inspector：返回固定 RepositoryContext 或抛出异常。

    duck typing：Orchestrator 只调用 inspect(query=..., repository_root=...)。
    """

    def __init__(
        self,
        context: RepositoryContext | None = None,
        error: Exception | None = None,
    ) -> None:
        self._context = context
        self._error = error
        self.calls = 0

    def inspect(
        self,
        *,
        query: str,
        repository_root: Path,
        top_k: int = 5,
        budget_tokens: int = 1024,
    ) -> RepositoryContext:
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._context is None:
            raise RuntimeError("FakeInspector 未注入 context 也未注入 error")
        return self._context


def _ctx() -> RepositoryContext:
    return RepositoryContext(
        summary="任务: x | 相关文件: 1 | 候选总数: 1",
        relevant_files=("src/auth/service.py",),
        relevant_symbols=("AuthService",),
    )


def _real_orchestrator(repo_copy: Path, planner) -> SingleAgentOrchestrator:
    return SingleAgentOrchestrator(
        inspector=RepositoryInspector(ContextApplicationService()),
        planner=planner,
        repository_root=repo_copy,
    )


def _hash_dir(root: Path) -> str:
    """目录内容指纹（不含元数据，只读文件字节）。"""
    digest = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            digest.update(f.read_bytes())
    return digest.hexdigest()


# ===================================================================
# 正常路径
# ===================================================================

class TestHappyPath:
    """普通任务 → READY。"""

    def test_full_pipeline_reaches_ready(self, repo_copy: Path) -> None:
        """验收(管线走通): 真实 Context Engine + MockPlanner →
        status==READY、plan/repo_context 非空、task 保存原话。"""
        orchestrator = _real_orchestrator(repo_copy, MockPlanner(plan=_plan()))

        result = orchestrator.run(
            request="AuthService refresh 的完整链路",
            task_id="t-001",
        )

        assert result.status == TaskStatus.READY
        assert result.plan is not None
        assert len(result.plan.steps) == 2
        assert result.repo_context is not None
        assert result.repo_context.relevant_files
        assert result.task is not None
        assert result.task.original_request == "AuthService refresh 的完整链路"
        assert result.error is None


# ===================================================================
# 失败路径
# ===================================================================

class TestFailurePaths:
    """空输入 / Planner 异常 / 非法 Plan。"""

    def test_empty_request_fails_fast_without_calling_planner(
        self, tmp_path: Path
    ) -> None:
        """验收(空任务早失败): 空串 → FAILED、error 含原因、
        **Planner 零调用**（证明没浪费 Token）。"""
        planner = MockPlanner(plan=_plan())
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=planner,
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="", task_id="t-empty")

        assert result.status == TaskStatus.FAILED
        assert result.task is None
        assert "ValidationError" in (result.error or "")
        assert planner.calls == []

    def test_whitespace_request_fails_fast(self, tmp_path: Path) -> None:
        """验收(空任务早失败): 纯空白同样早失败。"""
        planner = MockPlanner(plan=_plan())
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=planner,
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="   ", task_id="t-ws")

        assert result.status == TaskStatus.FAILED
        assert planner.calls == []

    def test_planner_exception_yields_failed_not_raise(
        self, tmp_path: Path
    ) -> None:
        """验收(Planner 异常→FAILED): run 不抛异常，
        status==FAILED、error 含异常类型名。"""
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=FailingPlanner(error=RuntimeError("model api down")),
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="修复登录超时", task_id="t-p")

        assert result.status == TaskStatus.FAILED
        assert "RuntimeError" in (result.error or "")
        assert result.events[-1].event_type == AgentEventType.TASK_FAILED

    def test_empty_steps_plan_rejected_with_validation_event(
        self, tmp_path: Path
    ) -> None:
        """验收(Plan 至少一个 Step): 注入 steps=() 的 Plan →
        FAILED，事件序列含 plan.validation_failed。"""
        empty_plan = Plan(plan_id="p", task_id="t", steps=())
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=empty_plan),
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="修复登录超时", task_id="t-empty-plan")

        assert result.status == TaskStatus.FAILED
        assert result.error == "plan_validation_failed"
        types = [e.event_type.value for e in result.events]
        assert "plan.validation_failed" in types

    def test_duplicate_step_ids_rejected(self, tmp_path: Path) -> None:
        """验收(Plan 校验): 重复 step_id 的 Plan → FAILED。"""
        dup_plan = Plan(
            plan_id="p", task_id="t",
            steps=(
                PlanStep(step_id="P1", title="a", description="a"),
                PlanStep(step_id="P1", title="b", description="b"),
            ),
        )
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=dup_plan),
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="x", task_id="t-dup")

        assert result.status == TaskStatus.FAILED
        assert result.error == "plan_validation_failed"


# ===================================================================
# 事件序列（Observability）
# ===================================================================

class TestEventSequence:
    """事件序列与事件数据断言。"""

    EXPECTED_SEQUENCE = (
        "task.created",
        "task.status_changed",             # CREATED → INSPECTING
        "repository.inspection_started",
        "repository.inspection_completed",
        "task.status_changed",             # INSPECTING → PLANNING
        "plan.started",
        "plan.created",
        "task.status_changed",             # PLANNING → READY
        "task.ready",
    )

    def test_exact_event_sequence(self, tmp_path: Path) -> None:
        """验收(事件序列): 成功路径事件类型序列逐位一致。"""
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="修复登录超时", task_id="t-seq")

        types = [e.event_type.value for e in result.events]
        assert tuple(types) == self.EXPECTED_SEQUENCE

    def test_status_changed_event_data(self, tmp_path: Path) -> None:
        """验收(事件序列): status_changed 事件 data 含
        from_status/to_status/reason。"""
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="x", task_id="t-data")

        changes = [
            e for e in result.events
            if e.event_type == AgentEventType.TASK_STATUS_CHANGED
        ]
        assert len(changes) == 3

        expected = [
            ("created", "inspecting", "task_spec_created"),
            ("inspecting", "planning", "inspection_completed"),
            ("planning", "ready", "valid_plan_created"),
        ]
        for event, (frm, to, reason) in zip(changes, expected):
            assert event.data["from_status"] == frm
            assert event.data["to_status"] == to
            assert event.data["reason"] == reason
            assert event.data["task_id"] == "t-data"

    def test_plan_created_event_data(self, tmp_path: Path) -> None:
        """验收(事件序列): plan.created 事件 data 含
        step_count/planner_ms/plan_id/version。"""
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
        )

        result = orchestrator.run(request="x", task_id="t-plan-data")

        plan_created = next(
            e for e in result.events
            if e.event_type == AgentEventType.PLAN_CREATED
        )
        assert plan_created.data["plan_id"] == "t-001-plan-v1"
        assert plan_created.data["version"] == 1
        assert plan_created.data["step_count"] == 2
        assert isinstance(plan_created.data["planner_ms"], int)


# ===================================================================
# 零副作用
# ===================================================================

class TestZeroSideEffect:
    """READY 路径磁盘零变更。"""

    def test_run_does_not_modify_disk(self, tmp_path: Path) -> None:
        """验收(磁盘零变更): run 前后目录内容指纹一致。"""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "a.py").write_text("x = 1\n")
        (repo_dir / "b.md").write_text("doc\n")

        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=repo_dir,
        )

        before = _hash_dir(repo_dir)
        result = orchestrator.run(request="x", task_id="t-zero")
        after = _hash_dir(repo_dir)

        assert result.status == TaskStatus.READY
        assert before == after

    def test_failed_run_does_not_modify_disk(self, tmp_path: Path) -> None:
        """验收(磁盘零变更): 失败路径同样不修改磁盘。"""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "a.py").write_text("x = 1\n")

        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=FailingPlanner(error=RuntimeError("boom")),
            repository_root=repo_dir,
        )

        before = _hash_dir(repo_dir)
        result = orchestrator.run(request="x", task_id="t-zero-fail")
        after = _hash_dir(repo_dir)

        assert result.status == TaskStatus.FAILED
        assert before == after
