"""W4D4 Step 0：K1/K3 状态机闸门测试。

对应 day4.md 附录工程地图 Step 0 验收：
- K1a：VERIFYING → PAUSED 合法（验证期 Ctrl+C 的前提）
- K1b：execute_plan_step 期间 KeyboardInterrupt → task PAUSED、
       step 保持 RUNNING、不向调用方抛异常
- K3： PAUSED → PLANNING 合法（规划期暂停可恢复）；既有恢复面不回归

Git 隔离：全部使用 pytest tmp_path 下的独立临时仓库 + local identity，
不触碰主仓库与 tests/fixtures（AGENTS.md Test Isolation）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from codeteam.agent.orchestrator import SingleAgentOrchestrator
from codeteam.events import AgentEventType
from codeteam.git.workspace import GitWorkspace
from codeteam.planning.models import Plan, PlanStep, PlanStepStatus
from codeteam.planning.planner import RepositoryContext
from codeteam.repair.models import RepairContext
from codeteam.task.models import create_task_spec
from codeteam.task.state import (
    InvalidTransitionError,
    TaskState,
    TaskStatus,
)
from codeteam.verification.models import (
    VerificationKind,
    VerificationRequest,
)
from codeteam.verification.service import VerificationService

GIT_TIMEOUT_SECONDS = 10.0


# ── 状态机层（K1a / K3）────────────────────────────────────


class TestStateMachineGates:
    """TASK_TRANSITIONS 补齐后必须成立的转移契约。"""

    def test_verifying_can_pause(self) -> None:
        """K1a：VERIFYING → PAUSED 合法。

        证明：验证期被 Ctrl+C 的任务能进入 PAUSED，
        而不是被迫 FAILED 或抛 InvalidTransitionError。
        """
        state = TaskState(task_id="t-1")
        state.transition_to(TaskStatus.INSPECTING)
        state.transition_to(TaskStatus.PLANNING)
        state.transition_to(TaskStatus.READY)
        state.transition_to(TaskStatus.IMPLEMENTING)
        state.transition_to(TaskStatus.VERIFYING)

        state.transition_to(TaskStatus.PAUSED, reason="user_interrupt")

        assert state.status is TaskStatus.PAUSED

    def test_paused_can_resume_to_planning(self) -> None:
        """K3：PAUSED → PLANNING 合法。

        证明：规划期暂停（PLANNING → PAUSED，W4D3 已有出口）
        之后能回到 PLANNING 继续规划，恢复面不再缺角。
        """
        state = TaskState(task_id="t-1")
        state.transition_to(TaskStatus.INSPECTING)
        state.transition_to(TaskStatus.PLANNING)
        state.transition_to(TaskStatus.PAUSED, reason="user_interrupt")

        state.transition_to(TaskStatus.PLANNING, reason="resume_replan")

        assert state.status is TaskStatus.PLANNING

    def test_paused_resume_surface_regression(self) -> None:
        """回归：PAUSED 既有恢复面 READY / IMPLEMENTING 不因 K3 收窄。"""
        for target in (
            TaskStatus.READY,
            TaskStatus.IMPLEMENTING,
            TaskStatus.PLANNING,
        ):
            state = TaskState(task_id="t-1")
            state.transition_to(TaskStatus.INSPECTING)
            state.transition_to(TaskStatus.PLANNING)
            state.transition_to(TaskStatus.PAUSED, reason="user_interrupt")
            state.transition_to(target, reason="resume")
            assert state.status is target

    def test_verifying_to_failed_still_legal(self) -> None:
        """回归：VERIFYING → FAILED 不因 K1 被破坏。"""
        state = TaskState(task_id="t-1")
        state.transition_to(TaskStatus.INSPECTING)
        state.transition_to(TaskStatus.PLANNING)
        state.transition_to(TaskStatus.READY)
        state.transition_to(TaskStatus.IMPLEMENTING)
        state.transition_to(TaskStatus.VERIFYING)

        state.transition_to(TaskStatus.FAILED, reason="unrecoverable")

        assert state.status is TaskStatus.FAILED
        assert state.is_terminal

    def test_terminal_still_rejects_pause(self) -> None:
        """回归：Terminal 状态（COMPLETED）仍拒绝任何转移，
        K1/K3 扩展没有打开 Terminal 出口。"""
        state = TaskState(task_id="t-1")
        state.transition_to(TaskStatus.INSPECTING)
        state.transition_to(TaskStatus.PLANNING)
        state.transition_to(TaskStatus.READY)
        state.transition_to(TaskStatus.IMPLEMENTING)
        state.transition_to(TaskStatus.VERIFYING)
        state.transition_to(TaskStatus.COMPLETED, reason="done")

        with pytest.raises(InvalidTransitionError):
            state.transition_to(TaskStatus.PAUSED, reason="late_interrupt")


# ── Orchestrator 层（K1b）──────────────────────────────────


def _run_git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        shell=False,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )


class _InterruptingRepairAgent:
    """propose_patch 第一次调用即抛 KeyboardInterrupt。

    模拟 Ctrl+C 落在修复循环内部的模型调用上。
    RepairLoop.run 的 except Exception 不会捕获它
    （KeyboardInterrupt 继承 BaseException），
    因此它会原生穿透到 execute_plan_step 的中断闸门。
    """

    def __init__(self) -> None:
        self.calls = 0

    def propose_patch(self, context: RepairContext) -> str:
        self.calls += 1
        raise KeyboardInterrupt()


class _FakeInspector:
    """duck-typing 仓库检查器（与 tests/agent 同模式）。"""

    def __init__(self, context: RepositoryContext) -> None:
        self._context = context

    def inspect(
        self,
        *,
        query: str,
        repository_root: Path,
    ) -> RepositoryContext:
        return self._context


class _StaticPlanner:
    """返回固定 Plan 的假 Planner（duck typing，Planner 是 Protocol）。"""

    def __init__(self, plan: Plan) -> None:
        self._plan = plan

    def create_plan(
        self,
        *,
        task,  # Protocol 签名占位（Planner 契约）
        repo_context,
    ) -> Plan:
        return self._plan


def _init_git_repo(tmp_path: Path) -> Path:
    """tmp_path 下初始化带 baseline commit 的独立临时仓库。"""
    _run_git(tmp_path, "init", "--quiet")
    _run_git(tmp_path, "config", "--local", "user.name", "Test User")
    _run_git(tmp_path, "config", "--local", "user.email", "t@example.com")
    (tmp_path / "m.py").write_text("def add(a, b):\n    return a + b\n")
    _run_git(tmp_path, "add", "--all")
    _run_git(tmp_path, "commit", "--quiet", "--allow-empty", "-m", "baseline")
    return tmp_path


def _ready_state(task_id: str) -> TaskState:
    state = TaskState(task_id=task_id)
    state.transition_to(TaskStatus.INSPECTING)
    state.transition_to(TaskStatus.PLANNING)
    state.transition_to(TaskStatus.READY)
    return state


def _ctx() -> RepositoryContext:
    return RepositoryContext(
        summary="tiny repo",
        relevant_files=("m.py",),
    )


def _plan() -> Plan:
    step = PlanStep(
        step_id="P1",
        title="Fix add",
        description="fix add implementation",
    )
    return Plan(
        plan_id="plan-1",
        task_id="t-step",
        steps=(step,),
    )


def _target_request(task_id: str, cwd: Path) -> VerificationRequest:
    return VerificationRequest(
        verification_id="vt-1",
        task_id=task_id,
        plan_step_id="P1",
        kind=VerificationKind.TARGETED_TEST,
        argv=("true",),
        cwd=str(cwd),
        purpose="verify fix",
    )


def _make_orchestrator(tmp_path: Path) -> SingleAgentOrchestrator:
    return SingleAgentOrchestrator(
        inspector=cast(Any, _FakeInspector(_ctx())),
        planner=_StaticPlanner(_plan()),
        repository_root=tmp_path,
        verification_service=VerificationService(),
        workspace=GitWorkspace(tmp_path),
    )


class TestExecutePlanStepInterrupt:
    """K1b：execute_plan_step 的 KeyboardInterrupt → PAUSED 闸门。"""

    def test_interrupt_pauses_task_not_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """K1b 主路径：修复循环中 Ctrl+C →
        - 不向调用方抛 KeyboardInterrupt
        - task 状态 PAUSED（经合法转移 IMPLEMENTING → PAUSED）
        - step 保持 RUNNING（中断不是 step 失败）
        - 事件含 task.paused（审计时间线完整）
        """
        _init_git_repo(tmp_path)
        task_id = "t-step"
        orchestrator = _make_orchestrator(tmp_path)
        task_state = _ready_state(task_id)
        plan_step = _plan().steps[0]
        agent = _InterruptingRepairAgent()

        result = orchestrator.execute_plan_step(
            task=create_task_spec(
                task_id=task_id,
                original_request="修复 add 函数",
            ),
            plan_step=plan_step,
            task_state=task_state,
            initial_patch="not-a-valid-diff",  # 先 PATCH_FAILED 进修复循环
            repair_agent=agent,
            target_request=_target_request(task_id, tmp_path),
            workspace_root=tmp_path,
        )

        assert agent.calls == 1  # 中断确实发生在修复循环内
        assert result.task_status is TaskStatus.PAUSED
        assert result.step_status is PlanStepStatus.RUNNING

        # 转移链：READY → IMPLEMENTING → PAUSED
        to_statuses = [h.to_status for h in task_state.history]
        assert to_statuses[-2:] == [
            TaskStatus.IMPLEMENTING,
            TaskStatus.PAUSED,
        ]

        types = [e.event_type for e in result.events]
        assert AgentEventType.REPAIR_STARTED in types
        assert AgentEventType.TASK_PAUSED in types
        # 暂停不是失败
        assert AgentEventType.TASK_FAILED not in types

    def test_interrupted_task_can_resume_implementing(
        self,
        tmp_path: Path,
    ) -> None:
        """中断后恢复面：PAUSED → IMPLEMENTING 可达（Day 4 Resume 的前提）。

        完整链：READY → IMPLEMENTING → PAUSED → IMPLEMENTING。
        """
        _init_git_repo(tmp_path)
        task_id = "t-step"
        orchestrator = _make_orchestrator(tmp_path)
        task_state = _ready_state(task_id)
        plan_step = _plan().steps[0]

        result = orchestrator.execute_plan_step(
            task=create_task_spec(
                task_id=task_id,
                original_request="修复 add 函数",
            ),
            plan_step=plan_step,
            task_state=task_state,
            initial_patch="not-a-valid-diff",
            repair_agent=_InterruptingRepairAgent(),
            target_request=_target_request(task_id, tmp_path),
            workspace_root=tmp_path,
        )
        assert result.task_status is TaskStatus.PAUSED

        # 模拟 Resume：从 PAUSED 回到 IMPLEMENTING 继续执行
        task_state.transition_to(
            TaskStatus.IMPLEMENTING, reason="session_resumed"
        )
        assert task_state.status is TaskStatus.IMPLEMENTING
