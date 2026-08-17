"""测试 VerificationService 映射逻辑（codeteam/verification/service.py）。

注入 FakeExecutor 确定性测试映射（day2.md 六十九~七十一节）：
- _to_command_request：语义层 → 执行层字段传递
- _interpret：7 种 CommandStatus → 6 种 VerificationStatus
- truncated 是 metadata 不是 status（day2.md 三十五节）
- 只有 FAILED 提取 failure_signature（三十七节）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.execution.models import (
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from codeteam.verification.models import (
    VerificationKind,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from codeteam.verification.service import VerificationService


def _request(**kwargs) -> VerificationRequest:
    base = {
        "verification_id": "v-001",
        "task_id": "t-001",
        "kind": VerificationKind.TARGETED_TEST,
        "argv": ("pytest", "tests/test_auth.py"),
        "cwd": "/worktree/t-001",
        "purpose": "verify timeout retry",
    }
    base.update(kwargs)
    return VerificationRequest(**base)


class _FakeExecutor:
    """注入的假执行器：返回预设 CommandResult，记录收到的 CommandRequest。"""

    def __init__(self, result: CommandResult) -> None:
        self._result = result
        self.last_request: CommandRequest | None = None

    def execute(
        self, request: CommandRequest, *, approval_grant=None
    ) -> CommandResult:
        self.last_request = request
        return self._result


class _RaisingExecutor:
    """总是抛异常的执行器（模拟执行层崩溃）。"""

    def execute(self, request, *, approval_grant=None) -> CommandResult:
        raise RuntimeError("executor crashed")


def _result(**kwargs) -> CommandResult:
    base = {"status": CommandStatus.SUCCESS, "exit_code": 0}
    base.update(kwargs)
    return CommandResult(**base)


def _verify(executor, **request_kwargs) -> VerificationResult:
    service = VerificationService(executor=executor)
    return service.verify(
        _request(**request_kwargs), workspace_root=Path("/worktree/t-001")
    )


# ===================================================================
# _to_command_request
# ===================================================================

class TestToCommandRequest:
    """语义层 → 执行层转换（day2.md 七十节）。"""

    def test_field_mapping(self) -> None:
        """验收(转换): argv/cwd/timeout 传递、purpose→reason、
        workspace_root/task_id 正确。"""
        executor = _FakeExecutor(_result())
        _verify(executor, timeout_seconds=30.0)

        cmd = executor.last_request
        assert cmd.argv == ("pytest", "tests/test_auth.py")
        assert cmd.cwd == Path("/worktree/t-001")
        assert cmd.workspace_root == Path("/worktree/t-001")
        assert cmd.task_id == "t-001"
        assert cmd.reason == "verify timeout retry"  # purpose → reason
        assert cmd.timeout_seconds == 30.0


# ===================================================================
# _interpret：全状态映射
# ===================================================================

class TestInterpretMapping:
    """7 种 CommandStatus → 6 种 VerificationStatus。"""

    def test_success_exit_0_passed(self) -> None:
        """验收(映射): SUCCESS + exit 0 → PASSED。"""
        result = _verify(_FakeExecutor(_result()))
        assert result.status == VerificationStatus.PASSED
        assert result.exit_code == 0

    def test_truncated_exit_0_still_passed(self) -> None:
        """验收(day2.md 三十五节): truncated 是 metadata 不是 status——
        exit 0 + stdout 截断仍 PASSED。"""
        result = _verify(
            _FakeExecutor(
                _result(
                    exit_code=0,
                    stdout_truncated=True,
                    stdout="x" * 1000,
                )
            )
        )
        assert result.status == VerificationStatus.PASSED
        assert result.stdout_truncated is True

    def test_nonzero_exit_not_expected_failed_with_signature(self) -> None:
        """验收(映射): NONZERO_EXIT + exit 不在 expected → FAILED
        且提取 failure_signature。"""
        result = _verify(
            _FakeExecutor(
                _result(
                    status=CommandStatus.NONZERO_EXIT,
                    exit_code=1,
                    stderr=(
                        "FAILED tests/test_auth.py::test_x - "
                        "AssertionError: boom"
                    ),
                )
            )
        )
        assert result.status == VerificationStatus.FAILED
        assert result.failure_signature == (
            "tests/test_auth.py::test_x+AssertionError"
        )

    def test_exit_in_expected_passed(self) -> None:
        """验收(映射): exit 落在自定义 expected 集合 → PASSED
        （Oracle 是集合不是固定 0）。"""
        result = _verify(
            _FakeExecutor(_result(status=CommandStatus.NONZERO_EXIT, exit_code=1)),
            expected_exit_codes=(0, 1),
        )
        assert result.status == VerificationStatus.PASSED

    def test_timed_out(self) -> None:
        """验收(映射): TIMED_OUT → TIMED_OUT（不是 FAILED）。"""
        result = _verify(_FakeExecutor(_result(status=CommandStatus.TIMED_OUT)))
        assert result.status == VerificationStatus.TIMED_OUT

    def test_start_failed(self) -> None:
        """验收(映射): START_FAILED → START_FAILED
        （命令不存在是环境问题，不是代码问题）。"""
        result = _verify(
            _FakeExecutor(
                _result(
                    status=CommandStatus.START_FAILED,
                    error="command not found",
                )
            )
        )
        assert result.status == VerificationStatus.START_FAILED
        assert "command not found" in result.summary

    @pytest.mark.parametrize(
        "command_status",
        [
            CommandStatus.POLICY_DENIED,
            CommandStatus.APPROVAL_DENIED,
            CommandStatus.APPROVAL_REQUIRED,
        ],
    )
    def test_blocked_states(self, command_status: CommandStatus) -> None:
        """验收(映射): POLICY_DENIED/APPROVAL_DENIED/APPROVAL_REQUIRED
        → BLOCKED（代码还没被真正验证）。"""
        result = _verify(
            _FakeExecutor(
                _result(
                    status=command_status,
                    reasons=["policy said no"],
                )
            )
        )
        assert result.status == VerificationStatus.BLOCKED

    def test_unknown_status_inconclusive(self) -> None:
        """验收(映射): 防御分支——未来新增 CommandStatus 成员
        不会静默误判，落入 INCONCLUSIVE。"""
        from enum import Enum

        class _FutureStatus(str, Enum):
            FUTURE = "future_status"

        future = CommandResult.model_construct(
            status=_FutureStatus.FUTURE, exit_code=None
        )
        result = _verify(_FakeExecutor(future))
        assert result.status == VerificationStatus.INCONCLUSIVE

    def test_non_failed_statuses_have_no_signature(self) -> None:
        """验收(signature): 非 FAILED 状态不提取 failure_signature——
        TIMED_OUT 等没有行为失败证据。"""
        result = _verify(
            _FakeExecutor(
                _result(
                    status=CommandStatus.TIMED_OUT,
                    stderr="FAILED tests/x.py::test_a - AssertionError: x",
                )
            )
        )
        assert result.status == VerificationStatus.TIMED_OUT
        assert result.failure_signature is None


# ===================================================================
# verify() 行为
# ===================================================================

class TestVerifyBehavior:
    """verify() 的异常行为契约。"""

    def test_executor_exception_propagates(self) -> None:
        """记录当前契约：执行层崩溃（executor 抛异常）会向上传播，
        由 Orchestrator 总闸门转 Task FAILED。

        注意：这与"执行失败映射为结构化状态"不同——CommandStatus
        表达的是**正常返回的执行结果**；executor 本身崩溃是 Runtime
        缺陷，掩盖它会让调用方误以为验证"无结论"。
        """
        with pytest.raises(RuntimeError, match="executor crashed"):
            _verify(_RaisingExecutor())

    def test_verify_returns_result_not_raises_for_statuses(self) -> None:
        """验收(verify): 所有 CommandStatus（正常返回路径）都映射为
        结构化 VerificationResult，不抛异常。"""
        for status in (
            CommandStatus.SUCCESS,
            CommandStatus.NONZERO_EXIT,
            CommandStatus.TIMED_OUT,
            CommandStatus.START_FAILED,
            CommandStatus.POLICY_DENIED,
            CommandStatus.APPROVAL_DENIED,
            CommandStatus.APPROVAL_REQUIRED,
        ):
            result = _verify(_FakeExecutor(_result(status=status, exit_code=0)))
            assert isinstance(result, VerificationResult)
