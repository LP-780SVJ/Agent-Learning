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
import sys
from pathlib import Path

import pytest

from codeteam.agent.inspection import RepositoryInspector
from codeteam.agent.orchestrator import SingleAgentOrchestrator
from codeteam.application.build_context import ContextApplicationService
from codeteam.events import AgentEventType
from codeteam.git.workspace import GitWorkspace
from codeteam.planning.models import Plan, PlanStep, PlanStepStatus, create_plan
from codeteam.planning.planner import (
    FailingPlanner,
    MockPlanner,
    RepositoryContext,
)
from codeteam.repair.loop import MockRepairAgent
from codeteam.task.models import TaskSpec, create_task_spec
from codeteam.task.state import TaskState, TaskStatus
from codeteam.verification.models import VerificationKind, VerificationRequest
from codeteam.verification.service import VerificationService

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


# ===================================================================
# F2 回归：失败路径补发 status_changed 事件
# ===================================================================

class TestFailureStatusChangedEvent:
    """F2 回归: _fail 必须补发 →FAILED 的 status_changed 事件。

    对应 day1.md 九十三节：每次状态变化都要记录 from/to/reason。
    """

    def _run_failure(self, tmp_path: Path, planner):
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=planner,
            repository_root=tmp_path,
        )
        return orchestrator.run(request="x", task_id="t-f2")

    def test_planner_exception_emits_status_changed_to_failed(
        self, tmp_path: Path
    ) -> None:
        """验收(F2): Planner 异常路径事件末尾为
        status_changed(to=failed) + task.failed。"""
        result = self._run_failure(
            tmp_path, FailingPlanner(error=RuntimeError("boom"))
        )

        assert result.status == TaskStatus.FAILED
        assert len(result.events) >= 2
        assert result.events[-2].event_type == AgentEventType.TASK_STATUS_CHANGED
        assert result.events[-1].event_type == AgentEventType.TASK_FAILED

        change = result.events[-2]
        assert change.data["to_status"] == "failed"
        assert change.data["from_status"] == "planning"
        assert "reason" in change.data

    def test_invalid_plan_emits_status_changed_to_failed(
        self, tmp_path: Path
    ) -> None:
        """验收(F2): 非法 Plan 路径同样补发 status_changed。"""
        empty_plan = Plan(plan_id="p", task_id="t", steps=())
        result = self._run_failure(tmp_path, MockPlanner(plan=empty_plan))

        assert result.status == TaskStatus.FAILED
        assert result.events[-2].event_type == AgentEventType.TASK_STATUS_CHANGED
        assert result.events[-2].data["to_status"] == "failed"
        assert result.events[-2].data["from_status"] == "planning"
        assert result.events[-1].event_type == AgentEventType.TASK_FAILED

    def test_empty_request_status_changed_from_created(self, tmp_path: Path) -> None:
        """验收(F2): 空输入早失败时 status_changed 的 from_status=created
        （失败发生在 CREATED 阶段）。"""
        result = self._run_failure(tmp_path, MockPlanner(plan=_plan()))
        # 注：_run_failure 用固定 request="x"（非空）。
        # 空输入场景单独构造，验证 CREATED→FAILED。
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
        )
        result = orchestrator.run(request="", task_id="t-f2-empty")

        assert result.status == TaskStatus.FAILED
        assert result.events[-2].event_type == AgentEventType.TASK_STATUS_CHANGED
        assert result.events[-2].data["from_status"] == "created"
        assert result.events[-2].data["to_status"] == "failed"
        assert result.events[-1].event_type == AgentEventType.TASK_FAILED


# ===================================================================
# Day 2：execute_plan_step 集成（day2.md 七十八~七十九节）
# ===================================================================

def _task_spec(task_id: str = "t-step") -> TaskSpec:
    return create_task_spec(task_id=task_id, original_request="fix x")


def _ready_state(task_id: str = "t-step") -> TaskState:
    """构造处于 READY 状态的 TaskState（走合法转移链）。"""
    state = TaskState(task_id=task_id)
    state.transition_to(TaskStatus.INSPECTING)
    state.transition_to(TaskStatus.PLANNING)
    state.transition_to(TaskStatus.READY)
    return state


def _step() -> PlanStep:
    return PlanStep(step_id="P1", title="Fix x", description="fix")


def _target_request(task_id: str, cwd: Path) -> VerificationRequest:
    return VerificationRequest(
        verification_id="vt",
        task_id=task_id,
        plan_step_id="P1",
        kind=VerificationKind.TARGETED_TEST,
        argv=(sys.executable, "-m", "pytest", "test_m.py", "-q"),
        cwd=str(cwd),
        purpose="verify fix",
    )


class _ScriptedService:
    """脚本化验证服务（duck typing：verify(request, *, workspace_root)）。"""

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self._index = 0

    def verify(self, request, *, workspace_root):
        if self._index >= len(self._results):
            raise AssertionError("结果耗尽")
        result = self._results[self._index]
        self._index += 1
        return result


class TestExecutePlanStep:
    """execute_plan_step 状态推进与事件（day2.md 七十八~七十九节）。"""

    def test_missing_dependencies_raises(self, tmp_path: Path) -> None:
        """验收(依赖守卫): 未注入 verification_service/workspace →
        RuntimeError 带明确消息。"""
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
            # 不注入 verification_service / workspace
        )

        with pytest.raises(RuntimeError, match="verification_service"):
            orchestrator.execute_plan_step(
                task=_task_spec(),
                plan_step=_step(),
                task_state=_ready_state(),
                initial_patch="x",
                repair_agent=MockRepairAgent(patches=[]),
                target_request=_target_request("t-step", tmp_path),
                workspace_root=tmp_path,
            )

    def test_success_progression(self, tmp_path: Path) -> None:
        """验收(七十八节): SUCCESS → step COMPLETED、task COMPLETED、
        转移链 READY→IMPLEMENTING→VERIFYING→COMPLETED、
        事件含 repair.started / repair.completed（repair_count）。"""
        import subprocess

        # 真实临时仓库：add 错误 + 失败测试，修复 Patch 让它通过
        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )

        git("init")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "m.py").write_text("def add(a, b):\n    return a - b\n")
        (tmp_path / "test_m.py").write_text(
            "from m import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        )
        git("add", "-A")
        git("commit", "-m", "b")

        task_id = "t-step"
        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
            verification_service=VerificationService(),
            workspace=GitWorkspace(tmp_path),
        )
        task_state = _ready_state(task_id)
        plan_step = _step()

        good_patch = (
            "diff --git a/m.py b/m.py\n"
            "--- a/m.py\n"
            "+++ b/m.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+    return a + b\n"
        )

        result = orchestrator.execute_plan_step(
            task=_task_spec(task_id),
            plan_step=plan_step,
            task_state=task_state,
            initial_patch=good_patch,
            repair_agent=MockRepairAgent(patches=[]),
            target_request=_target_request(task_id, tmp_path),
            workspace_root=tmp_path,
        )

        assert result.task_status == TaskStatus.COMPLETED
        assert result.step_status == PlanStepStatus.COMPLETED
        # 转移链：READY→IMPLEMENTING→VERIFYING→COMPLETED
        to_statuses = [h.to_status for h in task_state.history]
        assert to_statuses[-3:] == [
            TaskStatus.IMPLEMENTING,
            TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
        ]
        types = [e.event_type for e in result.events]
        assert AgentEventType.REPAIR_STARTED in types
        completed_events = [
            e
            for e in result.events
            if e.event_type == AgentEventType.REPAIR_COMPLETED
        ]
        assert completed_events
        assert completed_events[0].data["repair_count"] == 0

    def test_exhausted_progression(self, tmp_path: Path) -> None:
        """验收(七十九节): REPAIR_EXHAUSTED → step FAILED、task FAILED、
        事件含 repair.exhausted 与 →failed 的 status_changed。"""
        import subprocess as sp

        from codeteam.verification.models import VerificationResult, VerificationStatus

        def git(*args: str) -> None:
            sp.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "m.py").write_text("x = 1\n")
        git("add", "-A")
        git("commit", "-m", "b")

        fail = VerificationResult(
            verification_id="vt",
            status=VerificationStatus.FAILED,
            exit_code=1,
            stderr="FAILED tests/test_x.py::test_a - AssertionError: boom",
            failure_signature="tests/test_x.py::test_a+AssertionError",
        )
        # initial + 2 repairs 全部失败
        svc = _ScriptedService([fail, fail, fail])

        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
            verification_service=svc,
            workspace=GitWorkspace(tmp_path),
        )
        task_state = _ready_state()
        plan_step = _step()

        result = orchestrator.execute_plan_step(
            task=_task_spec(),
            plan_step=plan_step,
            task_state=task_state,
            initial_patch=(
                "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
            ),
            repair_agent=MockRepairAgent(
                patches=[
                    ("diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                     "@@ -1 +1 @@\n-x = 2\n+x = 3\n"),
                    ("diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                     "@@ -1 +1 @@\n-x = 3\n+x = 4\n"),
                ]
            ),
            target_request=_target_request("t-step", tmp_path),
            workspace_root=tmp_path,
            max_repair_attempts=2,
        )

        assert result.task_status == TaskStatus.FAILED
        assert result.step_status == PlanStepStatus.FAILED
        types = [e.event_type for e in result.events]
        assert AgentEventType.REPAIR_EXHAUSTED in types
        # →failed 的 status_changed 存在
        failed_changes = [
            e
            for e in result.events
            if e.event_type == AgentEventType.TASK_STATUS_CHANGED
            and e.data.get("to_status") == "failed"
        ]
        assert failed_changes

    def test_execution_error_keeps_intermediate_state(
        self, tmp_path: Path
    ) -> None:
        """验收(七十九节): EXECUTION_ERROR → step 保持 RUNNING、
        task 保持 IMPLEMENTING（只有 budget exhausted 才标 FAILED）。"""
        import subprocess as sp

        from codeteam.verification.models import VerificationResult, VerificationStatus

        def git(*args: str) -> None:
            sp.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "m.py").write_text("x = 1\n")
        git("add", "-A")
        git("commit", "-m", "b")

        start_failed = VerificationResult(
            verification_id="vt", status=VerificationStatus.START_FAILED
        )

        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
            verification_service=_ScriptedService([start_failed]),
            workspace=GitWorkspace(tmp_path),
        )
        task_state = _ready_state()
        plan_step = _step()

        result = orchestrator.execute_plan_step(
            task=_task_spec(),
            plan_step=plan_step,
            task_state=task_state,
            initial_patch=(
                "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
            ),
            repair_agent=MockRepairAgent(patches=[]),
            target_request=_target_request("t-step", tmp_path),
            workspace_root=tmp_path,
        )

        assert result.task_status == TaskStatus.IMPLEMENTING
        assert result.step_status == PlanStepStatus.RUNNING
        types = [e.event_type for e in result.events]
        assert AgentEventType.REPAIR_FAILED in types

    def test_attempt_events_replayed(self, tmp_path: Path) -> None:
        """验收(事件回放): attempt 有 patch_hash → repair.patch_proposed；
        有 changed_files → repair.patch_applied。"""
        import subprocess as sp

        from codeteam.verification.models import VerificationResult, VerificationStatus

        def git(*args: str) -> None:
            sp.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "m.py").write_text("x = 1\n")
        git("add", "-A")
        git("commit", "-m", "b")

        fail = VerificationResult(
            verification_id="vt",
            status=VerificationStatus.FAILED,
            exit_code=1,
            stderr="FAILED t::a - AssertionError: boom",
            failure_signature="t::a+AssertionError",
        )

        orchestrator = SingleAgentOrchestrator(
            inspector=_FakeInspector(context=_ctx()),
            planner=MockPlanner(plan=_plan()),
            repository_root=tmp_path,
            verification_service=_ScriptedService([fail, fail]),
            workspace=GitWorkspace(tmp_path),
        )
        task_state = _ready_state()
        plan_step = _step()

        result = orchestrator.execute_plan_step(
            task=_task_spec(),
            plan_step=plan_step,
            task_state=task_state,
            initial_patch=(
                "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
            ),
            repair_agent=MockRepairAgent(
                patches=[
                    ("diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
                     "@@ -1 +1 @@\n-x = 2\n+x = 3\n"),
                ]
            ),
            target_request=_target_request("t-step", tmp_path),
            workspace_root=tmp_path,
            max_repair_attempts=1,
        )

        types = [e.event_type for e in result.events]
        assert AgentEventType.REPAIR_PATCH_PROPOSED in types
        assert AgentEventType.REPAIR_PATCH_APPLIED in types
        applied = [
            e
            for e in result.events
            if e.event_type == AgentEventType.REPAIR_PATCH_APPLIED
        ]
        assert applied[0].data["attempt_no"] == 1
        assert "m.py" in applied[0].data["changed_files"]
