"""W4D5 Step 6（K2 接线）：Recovery 执行器的公共路径测试。

覆盖（用户任务书第 3 节）：
- RecoveryPolicy 返回 COMPACT 时会调用 compaction（经 run() 公共路径）
- compaction 成功 → recovery.completed + retry once（planner 真实第二次调用）
- compaction 失败/未注入 → recovery.failed + terminal failure
- REREAD 同构验证（注：PATCH_APPLY 阶段当前无生产调用方，
  走 _execute_with_recovery 直接路径并如实标注——公共路径化
  属 execute_plan_step 接线后的范围）

对应 day5 §四十六 Model 矩阵之外的本日验收：K2 = W4D3 遗留的
「RECOVERY_COMPLETED / RECOVERY_FAILED 事件已有定义、无发射方」。

工程约束：全 Fake（inspector/planner/compactor/rereader），无网络、
无 sleep、tmp_path 仅作 repository_root 占位。
"""
from __future__ import annotations

import pytest

from codeteam.agent.orchestrator import (
    SingleAgentOrchestrator,
    _TerminalFailure,
)
from codeteam.context.compaction import CompactionReason, CompactionRequest
from codeteam.events import AgentEvent, AgentEventType
from codeteam.failures.models import FailureStage
from codeteam.llm.error_mapper import (
    NormalizedModelError,
    NormalizedModelErrorCode,
)
from codeteam.llm.registry import ModelSelection
from codeteam.planning.models import Plan, PlanStep, PlanStepStatus
from codeteam.planning.planner import RepositoryContext
from codeteam.schemas.messages import Message
from codeteam.task.state import TaskState, TaskStatus

# ── 假对象 ───────────────────────────────────────────────


class _FakeInspector:
    def inspect(self, *, query: str, repository_root) -> RepositoryContext:
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


class _OverflowOncePlanner:
    """第 1 次抛归一化 CONTEXT_OVERFLOW，之后成功——
    驱动 run() 公共路径进入 COMPACT_CONTEXT 恢复分支。"""

    def __init__(self) -> None:
        self.calls = 0

    def create_plan(self, **kwargs) -> Plan:
        self.calls += 1
        if self.calls == 1:
            raise NormalizedModelError(
                message="This model's maximum context length is 128000 tokens",
                provider_id="openai-compatible",
                normalized_code=NormalizedModelErrorCode.CONTEXT_OVERFLOW,
            )
        return _plan()


class _RecordingCompactor:
    """记录 (request, messages) 并可编程失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[CompactionRequest, tuple[Message, ...]]] = []

    def compact(
        self,
        request: CompactionRequest,
        *,
        messages: tuple[Message, ...],
    ) -> object:
        self.calls.append((request, messages))
        if self.fail:
            raise RuntimeError("compactor exploded")
        return object()  # _try_compact 只关心是否抛异常


def _compaction_materials() -> tuple[CompactionRequest, tuple[Message, ...]]:
    request = CompactionRequest(
        session_id="ses_t",
        reason=CompactionReason.CONTEXT_OVERFLOW_RECOVERY,
        model_selection=ModelSelection(provider_id="p", model_id="m"),
        context_window_tokens=1000,
        current_context_tokens=900,
        target_context_tokens=500,
        recent_window_budget_tokens=100,
    )
    messages = (Message(role="user", content="x" * 50),)
    return request, messages


def _types(events: list[AgentEvent]) -> list[AgentEventType]:
    return [e.event_type for e in events]


def _orchestrator(
    tmp_path,
    planner,
    *,
    compactor=None,
    provider=None,
    rereader=None,
) -> SingleAgentOrchestrator:
    return SingleAgentOrchestrator(
        inspector=_FakeInspector(),
        planner=planner,
        repository_root=tmp_path,
        compactor=compactor,
        recovery_context_provider=provider,
        rereader=rereader,
    )


# ── COMPACT：run() 公共路径 ──────────────────────────────


class TestCompactRecoveryPublicPath:
    def test_compact_success_retries_once_and_completes(self, tmp_path) -> None:
        """验收：COMPACT 恢复 → compaction 执行 → recovery.completed →
        retry once → 任务 READY。planner.calls==2 证明重试真实发生，
        compactor 收到的正是 provider 给出的材料。"""
        planner = _OverflowOncePlanner()
        compactor = _RecordingCompactor()
        provider_calls: list[int] = []

        def provider():
            provider_calls.append(1)
            return _compaction_materials()

        orchestrator = _orchestrator(
            tmp_path, planner, compactor=compactor, provider=provider
        )
        result = orchestrator.run(request="修复登录超时", task_id="t-c1")

        assert result.status == TaskStatus.READY
        assert planner.calls == 2                      # retry once
        assert len(provider_calls) == 1
        assert len(compactor.calls) == 1

        types = _types(result.events)
        assert AgentEventType.RECOVERY_STARTED in types
        assert AgentEventType.RECOVERY_COMPLETED in types
        # COMPACT 不是 RETRY：绝不走重试等待路径
        assert AgentEventType.RETRY_SCHEDULED not in types

        started = next(
            e for e in result.events
            if e.event_type == AgentEventType.RECOVERY_STARTED
        )
        assert started.data["action"] == "compact_context"
        completed = next(
            e for e in result.events
            if e.event_type == AgentEventType.RECOVERY_COMPLETED
        )
        assert completed.data["action"] == "compact_context"

    def test_compactor_receives_provider_materials(self, tmp_path) -> None:
        """接线正确性：compactor 拿到的 (request, messages) 与
        recovery_context_provider 返回值同源（身份一致）。"""
        planner = _OverflowOncePlanner()
        compactor = _RecordingCompactor()
        expected_request, expected_messages = _compaction_materials()

        orchestrator = _orchestrator(
            tmp_path, planner,
            compactor=compactor,
            provider=lambda: (expected_request, expected_messages),
        )
        result = orchestrator.run(request="x", task_id="t-c2")

        assert result.status == TaskStatus.READY
        request, messages = compactor.calls[0]
        assert request is expected_request
        assert messages is expected_messages

    def test_compactor_not_injected_fails_terminal(self, tmp_path) -> None:
        """未注入 compactor（Day 3 兼容行为）：recovery.failed →
        FAILED 终态，planner 只调用 1 次（无任何重试）。"""
        planner = _OverflowOncePlanner()
        orchestrator = _orchestrator(tmp_path, planner)  # 无 compactor
        result = orchestrator.run(request="x", task_id="t-c3")

        assert result.status == TaskStatus.FAILED
        assert planner.calls == 1
        assert "compact_recovery_failed" in (result.error or "")
        types = _types(result.events)
        assert AgentEventType.RECOVERY_FAILED in types
        assert AgentEventType.RECOVERY_COMPLETED not in types

    def test_compactor_exception_fails_terminal(self, tmp_path) -> None:
        """compaction 执行异常 → recovery.failed → FAILED。"""
        planner = _OverflowOncePlanner()
        compactor = _RecordingCompactor(fail=True)
        orchestrator = _orchestrator(
            tmp_path, planner,
            compactor=compactor, provider=_compaction_materials,
        )
        result = orchestrator.run(request="x", task_id="t-c4")

        assert result.status == TaskStatus.FAILED
        assert "compact_recovery_failed" in (result.error or "")
        assert AgentEventType.RECOVERY_FAILED in _types(result.events)

    def test_provider_exception_fails_terminal(self, tmp_path) -> None:
        """材料构造失败（provider 抛异常）按恢复失败处理。"""
        def broken_provider():
            raise RuntimeError("no session materials")

        planner = _OverflowOncePlanner()
        orchestrator = _orchestrator(
            tmp_path, planner,
            compactor=_RecordingCompactor(),
            provider=broken_provider,
        )
        result = orchestrator.run(request="x", task_id="t-c5")

        assert result.status == TaskStatus.FAILED
        assert AgentEventType.RECOVERY_FAILED in _types(result.events)

    def test_repeated_overflow_bounded_by_attempt_loop(self, tmp_path) -> None:
        """持续 overflow：每次 COMPACT 成功但操作仍溢出 → 反复
        recovery.completed + 重试。恢复循环不无限：本用例让第 3 次
        成功，验证多轮 COMPACT 不破坏事件流与终态。"""

        class _OverflowTwicePlanner:
            def __init__(self) -> None:
                self.calls = 0

            def create_plan(self, **kwargs) -> Plan:
                self.calls += 1
                if self.calls <= 2:
                    raise NormalizedModelError(
                        message="maximum context length exceeded",
                        provider_id="p",
                        normalized_code=NormalizedModelErrorCode.CONTEXT_OVERFLOW,
                    )
                return _plan()

        planner = _OverflowTwicePlanner()
        orchestrator = _orchestrator(
            tmp_path, planner,
            compactor=_RecordingCompactor(),
            provider=_compaction_materials,
        )
        result = orchestrator.run(request="x", task_id="t-c6")

        assert result.status == TaskStatus.READY
        assert planner.calls == 3
        completed = [
            e for e in result.events
            if e.event_type == AgentEventType.RECOVERY_COMPLETED
        ]
        assert len(completed) == 2


# ── REREAD：直接路径（公共路径化待 execute_plan_step 接线）──


class TestRereadRecoveryDirectPath:
    """PATCH_APPLY 阶段尚无 run() 公共调用方（execute_plan_step
    未接线），REREAD 分支经 _execute_with_recovery 验证——
    与 W4D3 TestRecoveryLoopDirect 同一架构边界，如实标注。"""

    def test_reread_success_retries_operation(self, tmp_path) -> None:
        """rereader 成功 → recovery.completed(action=reread) →
        同一操作真实重试第二次成功。"""
        rereader_calls: list = []

        def rereader(failure) -> None:
            rereader_calls.append(failure)

        orchestrator = _orchestrator(
            tmp_path, _OverflowOncePlanner(), rereader=rereader
        )
        state = TaskState(task_id="t-r1")
        events: list[AgentEvent] = []
        attempts = {"n": 0}

        def action():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("patch does not apply")
            return "patched"

        result = orchestrator._execute_with_recovery(
            state=state,
            events=events,
            stage=FailureStage.PATCH_APPLY,
            operation="patch_apply",
            action=action,
        )

        assert result == "patched"
        assert attempts["n"] == 2
        assert len(rereader_calls) == 1
        completed = next(
            e for e in events
            if e.event_type == AgentEventType.RECOVERY_COMPLETED
        )
        assert completed.data["action"] == "reread_and_regenerate"
        assert AgentEventType.RETRY_SCHEDULED not in _types(events)

    def test_rereader_not_injected_fails_terminal(self, tmp_path) -> None:
        """未注入 rereader（Day 3 兼容）：recovery.failed + 终态。"""
        orchestrator = _orchestrator(tmp_path, _OverflowOncePlanner())
        state = TaskState(task_id="t-r2")
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

        assert "reread_recovery_failed" in str(excinfo.value)
        assert AgentEventType.RECOVERY_FAILED in _types(events)

    def test_rereader_exception_fails_terminal(self, tmp_path) -> None:
        def broken_rereader(failure) -> None:
            raise RuntimeError("reread io error")

        orchestrator = _orchestrator(
            tmp_path, _OverflowOncePlanner(), rereader=broken_rereader
        )
        state = TaskState(task_id="t-r3")
        events: list[AgentEvent] = []

        with pytest.raises(_TerminalFailure):
            orchestrator._execute_with_recovery(
                state=state,
                events=events,
                stage=FailureStage.PATCH_APPLY,
                operation="patch_apply",
                action=lambda: (_ for _ in ()).throw(
                    RuntimeError("patch does not apply")
                ),
            )
        assert AgentEventType.RECOVERY_FAILED in _types(events)
