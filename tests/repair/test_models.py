"""测试 Repair 数据模型（codeteam/repair/models.py）。

覆盖 day2.md 验收（三十九~四十七节）：
- RepairAttempt 是 Runtime Entity（frozen 审计记录、attempt_no >= 1）
- RepairLoopRunResult.repair_count
- failure_tail 有界尾部
- build_repair_context 有界反馈包
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeteam.git.models import PatchResult, PatchStatus
from codeteam.repair.models import (
    RepairAttempt,
    RepairLoopRunResult,
    RepairOutcome,
    RepairRunOutcome,
    build_repair_context,
    failure_tail,
)
from codeteam.task.models import TaskSpec
from codeteam.verification.models import VerificationResult, VerificationStatus


def _attempt(**kwargs) -> RepairAttempt:
    base = {
        "attempt_no": 1,
        "task_id": "t-001",
        "plan_step_id": "P3",
        "outcome": RepairOutcome.VERIFIED_FAILED,
    }
    base.update(kwargs)
    return RepairAttempt(**base)


# ===================================================================
# RepairAttempt
# ===================================================================

class TestRepairAttempt:
    """RepairAttempt 审计记录语义。"""

    def test_frozen_attempt(self) -> None:
        """验收(RepairAttempt): frozen——修复事实创建后不可改。"""
        attempt = _attempt()
        with pytest.raises(ValidationError):
            attempt.outcome = RepairOutcome.VERIFIED_PASSED

    def test_attempt_no_ge_1(self) -> None:
        """验收(RepairAttempt): attempt_no 从 1 起（initial patch
        不算 repair，day2.md 五十一节）。"""
        with pytest.raises(ValidationError):
            _attempt(attempt_no=0)
        with pytest.raises(ValidationError):
            _attempt(attempt_no=-1)

    def test_field_completeness(self) -> None:
        """验收(RepairAttempt): 全字段构造（signature/patch/checkpoint
        关联，day2.md 四十一节）。"""
        attempt = _attempt(
            checkpoint_id="cp-003",
            failure_signature="tests/x.py::test_a+AssertionError",
            diagnosis_summary="retry_count 在错误层级递减",
            patch_hash="abc123",
            changed_files=("src/auth/service.py",),
            verification_ids=("v-002",),
            outcome=RepairOutcome.VERIFIED_FAILED,
        )
        assert attempt.checkpoint_id == "cp-003"
        assert attempt.failure_signature == "tests/x.py::test_a+AssertionError"
        assert attempt.patch_hash == "abc123"
        assert attempt.changed_files == ("src/auth/service.py",)
        assert attempt.outcome == RepairOutcome.VERIFIED_FAILED

    def test_defaults(self) -> None:
        """验收(RepairAttempt): 可选字段默认值（checkpoint/patch 可空）。"""
        attempt = _attempt()
        assert attempt.checkpoint_id is None
        assert attempt.patch_hash is None
        assert attempt.changed_files == ()
        assert attempt.verification_ids == ()


# ===================================================================
# RepairLoopRunResult
# ===================================================================

class TestRepairLoopRunResult:
    """循环结果模型。"""

    def test_repair_count_matches_attempts(self) -> None:
        """验收(RepairLoopRunResult): repair_count == len(attempts)
        （周度评测 Mean Repair Attempts 的数据源）。"""
        attempts = (
            _attempt(attempt_no=1),
            _attempt(attempt_no=2),
        )
        result = RepairLoopRunResult(
            task_id="t-001",
            outcome=RepairRunOutcome.SUCCESS,
            attempts=attempts,
        )
        assert result.repair_count == 2

    def test_repair_count_zero_default(self) -> None:
        """验收(RepairLoopRunResult): 无 attempts 时 repair_count == 0。"""
        result = RepairLoopRunResult(
            task_id="t-001", outcome=RepairRunOutcome.SUCCESS
        )
        assert result.repair_count == 0


# ===================================================================
# failure_tail
# ===================================================================

class TestFailureTail:
    """有界尾部提取（day2.md 一百零八节）。"""

    def test_short_output_unchanged(self) -> None:
        """验收(failure_tail): 短输出原样返回。"""
        assert failure_tail("x\ny") == "x\ny"

    def test_long_output_keeps_last_max_lines(self) -> None:
        """验收(failure_tail): 长输出只留最后 max_lines 行。"""
        long = "\n".join(f"line {i}" for i in range(100))
        tail = failure_tail(long, max_lines=10)
        assert len(tail.splitlines()) == 10
        assert tail.startswith("line 90")
        assert tail.endswith("line 99")

    def test_strips_whitespace(self) -> None:
        """验收(failure_tail): 首尾空白被去掉。"""
        assert failure_tail("  a\nb  \n") == "a\nb"


# ===================================================================
# build_repair_context
# ===================================================================

class TestBuildRepairContext:
    """有界反馈包组装（day2.md 四十七节）。"""

    def test_field_sources(self) -> None:
        """验收(RepairContext): goal/plan_step_title/constraints 来自
        task；changed_files 来自 patch_result；failure_tail 有界。"""
        task = TaskSpec(
            task_id="t-001",
            original_request="修复登录超时",
            goal="登录超时自动重试",
            constraints=("不能修改公开 API",),
        )
        target_result = VerificationResult(
            verification_id="v-001",
            status=VerificationStatus.FAILED,
            exit_code=1,
            stderr="FAILED tests/test_x.py::test_a - AssertionError: boom",
            failure_signature="tests/test_x.py::test_a+AssertionError",
            summary="FAILED: exit 1",
        )
        patch_result = PatchResult(
            status=PatchStatus.APPLIED,
            patch_sha256="h1",
            affected_paths=["src/auth/service.py"],
            applied=True,
        )

        ctx = build_repair_context(
            task=task,
            plan_step_title="Fix timeout",
            target_result=target_result,
            patch_result=patch_result,
        )

        assert ctx.goal == "登录超时自动重试"
        assert ctx.plan_step_title == "Fix timeout"
        assert ctx.constraints == ("不能修改公开 API",)
        assert ctx.changed_files == ("src/auth/service.py",)
        assert ctx.failure_summary == "FAILED: exit 1"
        assert "AssertionError" in ctx.failure_tail
        assert ctx.previous_attempts == "(无历史修复)"

    def test_previous_attempts_summary(self) -> None:
        """验收(RepairContext): 历史 attempt 压缩成摘要行
        （防振荡的上下文基础）。"""
        task = TaskSpec(
            task_id="t", original_request="r", goal="g"
        )
        target_result = VerificationResult(
            verification_id="v", status=VerificationStatus.FAILED
        )
        patch_result = PatchResult(
            status=PatchStatus.APPLIED,
            patch_sha256="h",
            affected_paths=[],
            applied=True,
        )
        attempts = (
            _attempt(
                attempt_no=1,
                failure_signature="a+AssertionError",
                outcome=RepairOutcome.VERIFIED_FAILED,
            ),
        )

        ctx = build_repair_context(
            task=task,
            plan_step_title="P1",
            target_result=target_result,
            patch_result=patch_result,
            previous_attempts=attempts,
        )

        assert "attempt #1" in ctx.previous_attempts
        assert "a+AssertionError" in ctx.previous_attempts
        assert "verified_failed" in ctx.previous_attempts
