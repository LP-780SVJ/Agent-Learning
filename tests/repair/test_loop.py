"""测试 RepairLoop（codeteam/repair/loop.py）。

覆盖 day2.md 六十~六十七节 Required Tests（T1-T7）与
六十七节 Extra Tests（T8-T15）+ 一百一十六节 Mock 原则。

隔离策略：真实临时 Git 仓库（conftest.git_repo）+
ScriptedVerificationService（外部执行结果脚本化）+
MockRepairAgent（外部模型 Mock）——状态机/循环/级联逻辑全部真实执行。
"""

from __future__ import annotations

from pathlib import Path

from codeteam.git.workspace import GitWorkspace
from codeteam.repair.loop import MockRepairAgent, RepairLoop
from codeteam.repair.models import (
    RepairLoopOutcome,
    RepairOutcome,
    RepairRunOutcome,
)
from codeteam.task.models import TaskSpec
from codeteam.verification.models import (
    VerificationKind,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)

from .conftest import make_patch

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _task() -> TaskSpec:
    return TaskSpec(task_id="t-001", original_request="fix", goal="fix")


def _req(verification_id: str, kind: VerificationKind) -> VerificationRequest:
    return VerificationRequest(
        verification_id=verification_id,
        task_id="t-001",
        plan_step_id="P1",
        kind=kind,
        argv=("pytest", "tests/test_x.py"),
        cwd="/tmp/x",
        purpose="p",
    )


def _ok() -> VerificationResult:
    return VerificationResult(
        verification_id="vt", status=VerificationStatus.PASSED, exit_code=0
    )


def _fail(
    signature: str = "tests/test_x.py::test_a+AssertionError",
    marker: str = "AssertionError: boom",
) -> VerificationResult:
    return VerificationResult(
        verification_id="vt",
        status=VerificationStatus.FAILED,
        exit_code=1,
        stderr=f"FAILED tests/test_x.py::test_a - {marker}",
        failure_signature=signature,
        summary="FAILED: exit 1",
    )


def _status_result(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(verification_id="vt", status=status)


# ===================================================================
# MockRepairAgent（day2.md 一百一十六节）
# ===================================================================

class TestMockRepairAgent:
    """MockRepairAgent 队列语义与审计。"""

    def test_returns_patches_in_queue_order(self) -> None:
        """验收(Mock): 按队列顺序返回注入的 Patch。"""
        agent = MockRepairAgent(patches=["p1", "p2"])
        from codeteam.repair.models import RepairContext

        ctx = RepairContext(goal="g", plan_step_title="P1")
        assert agent.propose_patch(ctx) == "p1"
        assert agent.propose_patch(ctx) == "p2"

    def test_exhausted_returns_empty_string(self) -> None:
        """验收(Mock): 队列耗尽后返回空串（模拟"无法生成"）。"""
        from codeteam.repair.models import RepairContext

        agent = MockRepairAgent(patches=[])
        assert agent.propose_patch(RepairContext(goal="g", plan_step_title="P")) == ""

    def test_calls_record_contexts(self) -> None:
        """验收(Mock): calls 记录收到的 RepairContext（断言调用次数）。"""
        from codeteam.repair.models import RepairContext

        agent = MockRepairAgent(patches=["p"])
        ctx = RepairContext(goal="g", plan_step_title="P1")
        agent.propose_patch(ctx)
        assert len(agent.calls) == 1
        assert agent.calls[0] is ctx


# ===================================================================
# run_candidate（day2.md T12）
# ===================================================================

class TestRunCandidate:
    """单次候选评估语义。"""

    def test_patch_failed_skips_verification(self, git_repo: Path) -> None:
        """验收(T12): Patch 无法 apply → PATCH_FAILED 且验证未执行。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_ok()])
        loop = RepairLoop(
            verification_service=svc, workspace=GitWorkspace(git_repo)
        )
        # 错误 context（文件是 x = 1）
        bad_patch = make_patch("x = 99", "x = 100")

        result = loop.run_candidate(
            task_id="t-001",
            plan_step_id="P1",
            patch=bad_patch,
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
        )

        assert result.outcome is RepairLoopOutcome.PATCH_FAILED
        assert result.target_result is None
        assert svc.called_verification_ids == []  # 验证未被调用

    def test_target_failed(self, git_repo: Path) -> None:
        """验收(run_candidate): apply 成功 + Target FAILED → TARGET_FAILED。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_fail()])
        loop = RepairLoop(
            verification_service=svc, workspace=GitWorkspace(git_repo)
        )

        result = loop.run_candidate(
            task_id="t-001",
            plan_step_id="P1",
            patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
        )

        assert result.outcome is RepairLoopOutcome.TARGET_FAILED
        assert result.target_result.status is VerificationStatus.FAILED

    def test_target_passed(self, git_repo: Path) -> None:
        """验收(run_candidate): apply 成功 + Target PASSED → TARGET_PASSED。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_ok()])
        loop = RepairLoop(
            verification_service=svc, workspace=GitWorkspace(git_repo)
        )

        result = loop.run_candidate(
            task_id="t-001",
            plan_step_id="P1",
            patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
        )

        assert result.outcome is RepairLoopOutcome.TARGET_PASSED


# ===================================================================
# run()：Required Tests（day2.md 六十~六十七节）
# ===================================================================

class TestRepairLoopRun:
    """RepairLoop.run 循环语义。"""

    def _loop(self, git_repo: Path, svc) -> RepairLoop:
        return RepairLoop(
            verification_service=svc, workspace=GitWorkspace(git_repo)
        )

    def test_t1_first_patch_success(self, git_repo: Path) -> None:
        """验收(T1/六十节): 首次成功 → SUCCESS、repair_count==0、
        agent 零调用（不强行"再优化一次"）。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_ok()])
        agent = MockRepairAgent(patches=[])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
        )

        assert result.outcome is RepairRunOutcome.SUCCESS
        assert result.repair_count == 0
        assert len(agent.calls) == 0

    def test_t2_fail_once_then_success(self, git_repo: Path) -> None:
        """验收(T2/六十一节): 首次失败第二次成功 → repair_count==1，
        且第一次 failure 确实进入 RepairContext。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_fail(marker="AssertionError: FIRST"), _ok()])
        agent = MockRepairAgent(patches=[make_patch("x = 2", "x = 3")])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
        )

        assert result.outcome is RepairRunOutcome.SUCCESS
        assert result.repair_count == 1
        assert len(agent.calls) == 1
        # 第一次失败证据进入了修复上下文
        assert "FIRST" in agent.calls[0].failure_tail
        assert result.attempts[0].outcome is RepairOutcome.VERIFIED_PASSED

    def test_t3_exhausted_no_extra_model_call(self, git_repo: Path) -> None:
        """验收(T3/六十二节+T15): 连续失败到上限 → REPAIR_EXHAUSTED、
        attempts==max、agent 恰好被调用 max 次，绝无第 4 次。"""
        from .conftest import ScriptedVerificationService

        max_attempts = 2
        svc = ScriptedVerificationService([_fail(), _fail(), _fail()])
        agent = MockRepairAgent(
            patches=[make_patch("x = 2", "x = 3"), make_patch("x = 3", "x = 4")]
        )

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            max_repair_attempts=max_attempts,
        )

        assert result.outcome is RepairRunOutcome.REPAIR_EXHAUSTED
        assert len(result.attempts) == max_attempts
        assert len(agent.calls) == max_attempts  # 强不变量：无第 max+1 次

    def test_t4_regression_failure_triggers_repair(
        self, git_repo: Path
    ) -> None:
        """验收(T4/五十五节): Target PASS + Related Regression FAILED
        → 不直接 SUCCESS，以回归失败进入 Repair，修复后回归通过才成功。"""
        from .conftest import ScriptedVerificationService

        reg_fail = VerificationResult(
            verification_id="vr",
            status=VerificationStatus.FAILED,
            exit_code=1,
            stderr="FAILED tests/test_related.py::test_r - AssertionError: reg",
            failure_signature="tests/test_related.py::test_r+AssertionError",
        )
        reg_ok = VerificationResult(
            verification_id="vr", status=VerificationStatus.PASSED, exit_code=0
        )
        # 序列：initial target OK → regression FAIL → repair target OK → regression OK
        svc = ScriptedVerificationService([_ok(), reg_fail, _ok(), reg_ok])
        agent = MockRepairAgent(patches=[make_patch("x = 2", "x = 3")])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            related_regression_request=_req(
                "vr", VerificationKind.RELATED_REGRESSION
            ),
        )

        assert result.outcome is RepairRunOutcome.SUCCESS
        assert result.repair_count == 1
        assert len(result.regression_results) == 2
        # 修复的失败签名来自 regression（不是 target）
        assert result.attempts[0].failure_signature == (
            "tests/test_related.py::test_r+AssertionError"
        )

    def test_t5_start_failed_no_repair(self, git_repo: Path) -> None:
        """验收(T5/六十四节): 命令不存在 → EXECUTION_ERROR，
        agent 零调用（环境问题不误诊为代码问题）。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService(
            [_status_result(VerificationStatus.START_FAILED)]
        )
        agent = MockRepairAgent(patches=[make_patch("x = 2", "x = 3")])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
        )

        assert result.outcome is RepairRunOutcome.EXECUTION_ERROR
        assert len(agent.calls) == 0

    def test_t6_timed_out_no_repair(self, git_repo: Path) -> None:
        """验收(T6/六十五节): TIMED_OUT → EXECUTION_ERROR，
        不默认修改代码。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService(
            [_status_result(VerificationStatus.TIMED_OUT)]
        )
        agent = MockRepairAgent(patches=[])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
        )

        assert result.outcome is RepairRunOutcome.EXECUTION_ERROR
        assert len(agent.calls) == 0

    def test_t8_blocked_no_repair(self, git_repo: Path) -> None:
        """验收(T8/六十七节): BLOCKED → EXECUTION_ERROR，
        RepairAgent 零调用。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService(
            [_status_result(VerificationStatus.BLOCKED)]
        )
        agent = MockRepairAgent(patches=[])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
        )

        assert result.outcome is RepairRunOutcome.EXECUTION_ERROR
        assert len(agent.calls) == 0

    def test_t9_regression_blocked_inconclusive(self, git_repo: Path) -> None:
        """验收(T9): Target PASS 但 Regression BLOCKED → EXECUTION_ERROR
        （不默认修代码）。"""
        from .conftest import ScriptedVerificationService

        reg_blocked = VerificationResult(
            verification_id="vr", status=VerificationStatus.BLOCKED
        )
        svc = ScriptedVerificationService([_ok(), reg_blocked])
        agent = MockRepairAgent(patches=[])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            related_regression_request=_req(
                "vr", VerificationKind.RELATED_REGRESSION
            ),
        )

        assert result.outcome is RepairRunOutcome.EXECUTION_ERROR
        assert len(agent.calls) == 0

    def test_t10_same_failure_signature_repeated(self, git_repo: Path) -> None:
        """验收(T10/一百零七节): 同 failure_signature 连续出现可断言
        （振荡检测的数据基础）。"""
        from .conftest import ScriptedVerificationService

        same = "tests/test_x.py::test_a+AssertionError"
        svc = ScriptedVerificationService([_fail(signature=same), _fail(signature=same), _ok()])
        agent = MockRepairAgent(
            patches=[make_patch("x = 2", "x = 3"), make_patch("x = 3", "x = 4")]
        )

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            max_repair_attempts=3,
        )

        assert result.repair_count == 2
        assert result.attempts[0].failure_signature == same
        assert result.attempts[1].failure_signature == same

    def test_t11_empty_patch_stops_loop(self, git_repo: Path) -> None:
        """验收(T11/六十七节): RepairAgent 返回空串 → NO_PATCH →
        EXECUTION_ERROR，不进入无限循环。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_fail()])
        agent = MockRepairAgent(patches=[])  # 耗尽 → 返回空串

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            max_repair_attempts=3,
        )

        assert result.outcome is RepairRunOutcome.EXECUTION_ERROR
        assert len(agent.calls) == 1
        assert result.attempts[0].outcome is RepairOutcome.NO_PATCH

    def test_t13_checkpoint_hook_linkage(self, git_repo: Path) -> None:
        """验收(T13/四十二节): checkpoint_hook 每次 attempt 被调用且
        attempt_no 正确，checkpoint_id 写入 RepairAttempt。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_fail(), _ok()])
        agent = MockRepairAgent(patches=[make_patch("x = 2", "x = 3")])
        hook_calls: list[int] = []

        def hook(attempt_no: int) -> str:
            hook_calls.append(attempt_no)
            return f"cp-{attempt_no}"

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            checkpoint_hook=hook,
        )

        assert hook_calls == [1]
        assert result.attempts[0].checkpoint_id == "cp-1"

    def test_t14_regression_not_run_when_target_fails(
        self, git_repo: Path
    ) -> None:
        """验收(T14/六十七节): Target FAIL 时 Related Regression
        未被执行（避免浪费）。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_fail()])
        agent = MockRepairAgent(patches=[])

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            max_repair_attempts=0,
            related_regression_request=_req(
                "vr", VerificationKind.RELATED_REGRESSION
            ),
        )

        assert result.outcome is RepairRunOutcome.REPAIR_EXHAUSTED
        # 只调用了 target 验证，regression（"vr"）从未执行
        assert svc.called_verification_ids == ["vt"]

    def test_should_stop_interrupts(self, git_repo: Path) -> None:
        """验收(S4/八十节): should_stop 返回 True → INTERRUPTED，
        agent 不再被调用。"""
        from .conftest import ScriptedVerificationService

        svc = ScriptedVerificationService([_fail(), _fail()])
        agent = MockRepairAgent(patches=[make_patch("x = 2", "x = 3")])

        def stopper() -> bool:
            return len(agent.calls) >= 1

        result = self._loop(git_repo, svc).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            max_repair_attempts=3,
            should_stop=stopper,
        )

        assert result.outcome is RepairRunOutcome.INTERRUPTED
        assert len(agent.calls) == 1
        assert result.initial_candidate is not None


# ===================================================================
# RepairAgent 异常（loop.py 总闸门分支）
# ===================================================================

class TestAgentException:
    """repair_agent.propose_patch 抛异常 → NO_PATCH → EXECUTION_ERROR。"""

    def test_agent_exception_records_no_patch(self, git_repo: Path) -> None:
        """验收(总闸门): agent 抛异常 → attempts 记录 NO_PATCH、
        outcome=EXECUTION_ERROR、不再调用 agent。"""
        from .conftest import ScriptedVerificationService

        class _RaisingAgent:
            def __init__(self) -> None:
                self.calls = 0

            def propose_patch(self, context) -> str:
                self.calls += 1
                raise RuntimeError("model crashed")

        svc = ScriptedVerificationService([_fail()])
        agent = _RaisingAgent()

        result = RepairLoop(
            verification_service=svc, workspace=GitWorkspace(git_repo)
        ).run(
            task=_task(),
            plan_step_title="P1",
            initial_patch=make_patch("x = 1", "x = 2"),
            target_request=_req("vt", VerificationKind.TARGETED_TEST),
            workspace_root=git_repo,
            repair_agent=agent,
            max_repair_attempts=3,
        )

        assert result.outcome is RepairRunOutcome.EXECUTION_ERROR
        assert len(result.attempts) == 1
        assert result.attempts[0].outcome is RepairOutcome.NO_PATCH
        assert result.attempts[0].patch_hash is None
        assert agent.calls == 1  # 异常后不再调用
