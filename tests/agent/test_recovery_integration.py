"""tests/agent/test_recovery_integration.py — Orchestrator 恢复集成测试。

对应 day3.md §九十 分层原则的集成层：
断言真实行为（真的发生了第二次调用 / 真的等待了 / 真的进入
PAUSED），不是只断言 action == RETRY。

分层说明（诚实记录当前架构边界）：
- 异常路径集成：planner 抛出的异常经 _execute_with_recovery
  走「分类 → 决策 → 执行」。SECURITY 类里只有 SandboxError 家族
  是异常（I3 端到端验证）；PolicyDecision / ApprovalDecision /
  VerificationStatus 是结构化结果，在生产架构中于调用点（结果
  路径）处理，不走异常恢复层——它们的 no-retry 保证由
  tests/failures/ 的 classifier + policy 单测与 50 Case corpus
  （S01/S02/V01~V05）断言，本文件用 I3 验证同一 SECURITY→STOP
  分支的端到端行为。
"""

from __future__ import annotations

import pytest

from codeteam.agent.orchestrator import (
    SingleAgentOrchestrator,
    _TerminalFailure,
)
from codeteam.events import AgentEvent, AgentEventType
from codeteam.failures.models import (
    AgentErrorCode,
    FailureStage,
    RecoveryAction,
)
from codeteam.failures.retry import RetryPolicy
from codeteam.planning.models import Plan, PlanStep, PlanStepStatus
from codeteam.planning.planner import FailingPlanner, RepositoryContext
from codeteam.sandbox.errors import DockerUnavailableError
from codeteam.task.state import TaskState, TaskStatus

# ── 假对象 ─────────────────────────────────────────────────

class _FakeInspector:
    """假 Inspector：返回固定 RepositoryContext（duck typing）。"""

    def __init__(self, context: RepositoryContext | None = None):
        self._context = context or _ctx()

    def inspect(self, *, query: str, repository_root):
        return self._context


def _ctx() -> RepositoryContext:
    return RepositoryContext(
        summary="任务: x | 相关文件: 1 | 候选总数: 1",
        relevant_files=("src/auth/service.py",),
        relevant_symbols=("AuthService",),
    )


def _plan() -> Plan:
    return Plan(
        plan_id="p1",
        task_id="t",
        version=1,
        steps=(PlanStep(
            step_id="s1", title="t", description="d",
            status=PlanStepStatus.PENDING,
        ),),
        goal="g",
    )


class _FlakyPlanner:
    """前 N 次调用抛异常，之后成功——验证 RETRY 真实重调。"""

    def __init__(self, error: Exception, fail_times: int = 1):
        self._error = error
        self._fail_times = fail_times
        self.calls = 0

    def create_plan(self, **kwargs) -> Plan:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return _plan()


class _FakeStatusError(Exception):
    def __init__(self, message: str, status_code: int, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class _RecordingSleeper:
    """记录 delay，不真睡——测试绝不真实 sleep。"""

    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, delay_seconds: float) -> None:
        self.calls.append(delay_seconds)


def _orchestrator(tmp_path, planner, sleeper=None, retry_policy=None):
    return SingleAgentOrchestrator(
        inspector=_FakeInspector(),
        planner=planner,
        repository_root=tmp_path,
        retry_policy=retry_policy,
        sleeper=sleeper,
    )


def _types(events: list[AgentEvent]) -> list[AgentEventType]:
    return [e.event_type for e in events]


# ── 8 Required 的集成表达 ──────────────────────────────────

class TestRetrySuccessPath:
    """T1/T2：可重试失败 → RETRY → 真实第二次调用 → 成功。"""

    def test_rate_limit_retries_then_succeeds(self, tmp_path) -> None:
        """验收(rate limit→retry): FakePlanner 第 1 次抛 429、
        第 2 次成功 → 任务 READY。证明 Retry 真实发生：
        planner.calls == 2 且 sleeper 被调用 1 次——
        不是只断言 action == RETRY。"""
        sleeper = _RecordingSleeper()
        planner = _FlakyPlanner(
            _FakeStatusError("rate limited", 429), fail_times=1
        )
        orchestrator = _orchestrator(
            tmp_path, planner,
            sleeper=sleeper,
            retry_policy=RetryPolicy(jitter=False),
        )

        result = orchestrator.run(request="修复登录超时", task_id="t-rl")

        assert result.status == TaskStatus.READY
        assert planner.calls == 2
        assert len(sleeper.calls) == 1

    def test_model_timeout_retries_then_succeeds(self, tmp_path) -> None:
        """验收(model timeout→retry): MODEL_CALL + TimeoutError →
        MODEL_TIMEOUT → RETRY → 第二次成功。"""
        sleeper = _RecordingSleeper()
        planner = _FlakyPlanner(TimeoutError("slow"), fail_times=1)
        orchestrator = _orchestrator(
            tmp_path, planner,
            sleeper=sleeper,
            retry_policy=RetryPolicy(jitter=False),
        )

        result = orchestrator.run(request="x", task_id="t-to")

        assert result.status == TaskStatus.READY
        assert planner.calls == 2


class TestEventSequence:
    """验收 5：事件序列可重放 day3 §一百一十九 时间线。"""

    def test_rate_limit_recovery_event_timeline(self, tmp_path) -> None:
        """验收(事件时间线): 一次「模型调用失败→分类→决策→重试→
        成功」的事件类型顺序 + 关键 data 字段，与 day3 §一百一十九
        的时间线语义一致。"""
        sleeper = _RecordingSleeper()
        planner = _FlakyPlanner(
            _FakeStatusError("rate limited", 429), fail_times=1
        )
        orchestrator = _orchestrator(
            tmp_path, planner,
            sleeper=sleeper,
            retry_policy=RetryPolicy(jitter=False),
        )

        result = orchestrator.run(request="x", task_id="t-seq")
        assert result.status == TaskStatus.READY

        types = _types(result.events)
        # 期望子序列（顺序敏感）：
        expected = [
            AgentEventType.ERROR_DETECTED,
            AgentEventType.ERROR_CLASSIFIED,
            AgentEventType.RECOVERY_DECIDED,
            AgentEventType.RETRY_SCHEDULED,
            AgentEventType.RETRY_STARTED,
        ]
        # 子序列匹配：expected 必须以该顺序出现在 types 中
        pos = -1
        for want in expected:
            idx = types.index(want, pos + 1)
            assert idx > pos, f"事件 {want.value} 未按顺序出现"
            pos = idx

        # PLAN_CREATED（成功产物）必须在整个恢复序列之后
        assert types.index(AgentEventType.PLAN_CREATED) > pos

        # 关键 data 字段
        classified = next(
            e for e in result.events
            if e.event_type == AgentEventType.ERROR_CLASSIFIED
        )
        assert classified.data["category"] == "model"
        assert classified.data["code"] == "model_rate_limit"

        scheduled = next(
            e for e in result.events
            if e.event_type == AgentEventType.RETRY_SCHEDULED
        )
        assert scheduled.data["delay_seconds"] == 1.0  # jitter=False 精确
        assert scheduled.data["attempt"] == 2


class TestBudgetExhaustion:
    """I7 / T15：预算耗尽 → FAILED，无进一步操作。"""

    def test_retry_budget_exhausted_fails_task(self, tmp_path) -> None:
        """验收(I7): max_attempts=2 时连续 429 两次 →
        retry.exhausted 事件 → FAILED。第二次失败后不再执行任何
        操作（planner.calls == 2，sleeper 只睡了 1 次）。"""
        sleeper = _RecordingSleeper()
        planner = _FlakyPlanner(
            _FakeStatusError("rate limited", 429), fail_times=99
        )
        orchestrator = _orchestrator(
            tmp_path, planner,
            sleeper=sleeper,
            retry_policy=RetryPolicy(max_attempts=2, jitter=False),
        )

        result = orchestrator.run(request="x", task_id="t-ex")

        assert result.status == TaskStatus.FAILED
        assert planner.calls == 2
        assert len(sleeper.calls) == 1
        assert AgentEventType.RETRY_EXHAUSTED in _types(result.events)
        assert "max_attempts_exhausted" in (result.error or "")

    def test_terminal_failure_reason_contains_code(self, tmp_path) -> None:
        """验收(_TerminalFailure→FAILED): 永久失败（401）经
        _TerminalFailure → FAILED，reason 含错误码与来源类型。"""
        orchestrator = _orchestrator(
            tmp_path, FailingPlanner(error=_FakeStatusError("bad key", 401))
        )

        result = orchestrator.run(request="x", task_id="t-term")

        assert result.status == TaskStatus.FAILED
        assert "model_auth_failed" in (result.error or "")
        assert "_FakeStatusError" in (result.error or "")


class TestSecurityNoRetry:
    """I1/I2/I3 集成表达：SECURITY 类零重试。"""

    def test_sandbox_unavailable_never_retries(self, tmp_path) -> None:
        """验收(I3): 异常路径中唯一的 SECURITY 异常
        （DockerUnavailableError）→ STOP → FAILED。
        planner 只调用 1 次、sleeper 0 次、无 retry.* 事件——
        Fail Closed，Host fallback = 0（run 管线不执行任何命令）。"""
        sleeper = _RecordingSleeper()
        planner = _FlakyPlanner(
            DockerUnavailableError("docker down"), fail_times=99
        )
        orchestrator = _orchestrator(tmp_path, planner, sleeper=sleeper)

        result = orchestrator.run(request="x", task_id="t-sbx")

        assert result.status == TaskStatus.FAILED
        assert planner.calls == 1
        assert sleeper.calls == []
        types = _types(result.events)
        assert AgentEventType.RETRY_SCHEDULED not in types
        assert AgentEventType.RETRY_STARTED not in types
        decided = next(
            e for e in result.events
            if e.event_type == AgentEventType.RECOVERY_DECIDED
        )
        assert decided.data["action"] == RecoveryAction.STOP.value


class TestInterruptPauses:
    """I6：KeyboardInterrupt → PAUSED 而非 FAILED。"""

    def test_keyboard_interrupt_pauses_not_fails(self, tmp_path) -> None:
        """验收(Ctrl+C→PAUSED): planner 抛 KeyboardInterrupt →
        run() 不抛异常、status==PAUSED、task.paused 事件、
        retry=0——中断是控制流不是失败（day3 §四十五）。"""
        sleeper = _RecordingSleeper()
        orchestrator = _orchestrator(
            tmp_path,
            FailingPlanner(error=KeyboardInterrupt()),
            sleeper=sleeper,
        )

        result = orchestrator.run(request="x", task_id="t-int")

        assert result.status == TaskStatus.PAUSED
        assert result.task_state is not None
        assert result.task_state.status == TaskStatus.PAUSED
        assert AgentEventType.TASK_PAUSED in _types(result.events)
        assert sleeper.calls == []


class TestRecoveryLoopDirect:
    """_execute_with_recovery 的通用恢复路径（非 MODEL 阶段）。"""

    def _orchestrator_only(self, tmp_path, sleeper):
        return _orchestrator(tmp_path, _FlakyPlanner(_plan()), sleeper=sleeper)

    def test_patch_mismatch_never_retries_same_patch(self, tmp_path) -> None:
        """验收(I4): PATCH_APPLY 阶段的 context mismatch →
        REREAD_AND_REGENERATE，sleeper 0 次、无 retry.scheduled——
        同一个 Patch 重试必然失败。"""
        sleeper = _RecordingSleeper()
        orchestrator = self._orchestrator_only(tmp_path, sleeper)
        state = TaskState(task_id="t-patch")
        events: list[AgentEvent] = []

        with pytest.raises(_TerminalFailure) as excinfo:
            orchestrator._execute_with_recovery(
                state=state,
                events=events,
                stage=FailureStage.PATCH_APPLY,
                operation="patch_apply",
                action=lambda: (_ for _ in ()).throw(
                    RuntimeError("patch does not apply")
                ),
            )

        assert excinfo.value.failure.code == AgentErrorCode.PATCH_CONTEXT_MISMATCH
        assert sleeper.calls == []
        types = _types(events)
        assert AgentEventType.RETRY_SCHEDULED not in types
        decided = next(
            e for e in events
            if e.event_type == AgentEventType.RECOVERY_DECIDED
        )
        assert decided.data["action"] == RecoveryAction.REREAD_AND_REGENERATE.value

    def test_verification_timeout_repairs_not_retries(self, tmp_path) -> None:
        """验收(I5): VERIFICATION 阶段的超时 → TEST_TIMEOUT →
        REPAIR（recovery.decided=repair），不是盲目重跑测试
        （无 retry.scheduled、sleeper 0 次）。"""
        sleeper = _RecordingSleeper()
        orchestrator = self._orchestrator_only(tmp_path, sleeper)
        state = TaskState(task_id="t-verify")
        events: list[AgentEvent] = []

        with pytest.raises(_TerminalFailure) as excinfo:
            orchestrator._execute_with_recovery(
                state=state,
                events=events,
                stage=FailureStage.VERIFICATION,
                operation="verify",
                action=lambda: (_ for _ in ()).throw(TimeoutError("tests hang")),
            )

        assert excinfo.value.failure.code == AgentErrorCode.TEST_TIMEOUT
        assert sleeper.calls == []
        types = _types(events)
        assert AgentEventType.RETRY_SCHEDULED not in types
        decided = next(
            e for e in events
            if e.event_type == AgentEventType.RECOVERY_DECIDED
        )
        assert decided.data["action"] == RecoveryAction.REPAIR.value
