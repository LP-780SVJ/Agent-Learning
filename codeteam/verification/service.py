"""
VerificationService：语义层验证请求 → 安全执行 → 验证证据。

三层转换（day2.md 六十九节）：
VerificationRequest → CommandRequest → CommandResult → VerificationResult

VerificationService 不自己 subprocess.run——
执行永远走 Week 3 的 SafeCommandExecutor（Policy/Sandbox/Runner）。
"""
from __future__ import annotations

from pathlib import Path

from codeteam.execution.models import (
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from codeteam.execution.safe_executor import SafeCommandExecutor
from codeteam.verification.models import (
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
    extract_failure_signature,
)


class VerificationService:
    """把验证请求变成验证证据的服务。

    用法：
        service = VerificationService()  # 默认走真实安全链
        result = service.verify(
            request=req,
            workspace_root=Path("/worktree/t-001"),
        )

    测试可注入 FakeExecutor（duck typing：有 execute 方法即可），
    映射逻辑因此确定性可测。
    """

    def __init__(self, executor=None) -> None:
        """注入执行器；默认 SafeCommandExecutor（Week 3 安全链）。"""
        self._executor = executor or SafeCommandExecutor()

    # ── 主入口 ────────────────────────────────────────────

    def verify(
        self,
        request: VerificationRequest,
        *,
        workspace_root: Path,
    ) -> VerificationResult:
        """执行验证并解释结果。

        Args:
            request: 语义层验证请求。
            workspace_root: 任务 Worktree 根目录（安全链的路径边界）。

        Returns:
            VerificationResult。任何执行层失败都不会抛异常——
            全部映射为结构化状态。
        """
        command = self._to_command_request(
            request, workspace_root=workspace_root
        )
        cmd_result = self._executor.execute(command)
        return self._interpret(request, cmd_result)

    # ── 转换：语义层 → 执行层 ───────────────────────────────

    @staticmethod
    def _to_command_request(
        request: VerificationRequest,
        *,
        workspace_root: Path,
    ) -> CommandRequest:
        """VerificationRequest → CommandRequest。

        语义字段落到执行层：purpose 变成 reason（人可读审计），
        timeout/argv/cwd 原样传递。
        """
        return CommandRequest(
            argv=request.argv,
            cwd=Path(request.cwd),
            workspace_root=workspace_root,
            task_id=request.task_id,
            reason=request.purpose,
            timeout_seconds=request.timeout_seconds,
        )

    # ── 解释：进程视角 → 验证语义 ───────────────────────────

    @staticmethod
    def _interpret(
        request: VerificationRequest,
        cmd_result: CommandResult,
    ) -> VerificationResult:
        """CommandResult → VerificationResult。

        核心规则：PASS/FAIL 只由 exit code 是否落在
        expected_exit_codes 决定——Output Truncated 不改变判定，
        Runner 的 SUCCESS 只说明进程正常管理。
        """
        # 先处理"没有验证证据"的状态
        if cmd_result.status is CommandStatus.TIMED_OUT:
            vstatus = VerificationStatus.TIMED_OUT
            summary = "TIMED_OUT: 验证未在期限内完成"
        elif cmd_result.status is CommandStatus.START_FAILED:
            vstatus = VerificationStatus.START_FAILED
            summary = f"START_FAILED: {cmd_result.error or '命令无法启动'}"
        elif cmd_result.status in (
            CommandStatus.POLICY_DENIED,
            CommandStatus.APPROVAL_DENIED,
            CommandStatus.APPROVAL_REQUIRED,
        ):
            vstatus = VerificationStatus.BLOCKED
            reasons = "; ".join(cmd_result.reasons[:3])
            summary = f"BLOCKED: {reasons or cmd_result.status.value}"
        elif cmd_result.status in (
            CommandStatus.SUCCESS,
            CommandStatus.NONZERO_EXIT,
        ):
            # 有 exit code 证据 → 按 Oracle 判定
            if cmd_result.exit_code in request.expected_exit_codes:
                vstatus = VerificationStatus.PASSED
                summary = (
                    f"PASSED: exit {cmd_result.exit_code} "
                    f"in {cmd_result.duration_ms:.0f}ms"
                )
            else:
                vstatus = VerificationStatus.FAILED
                summary = (
                    f"FAILED: exit {cmd_result.exit_code} "
                    f"(expected {request.expected_exit_codes})"
                )
        else:
            # 防御分支：未来 CommandStatus 增加新值时不会静默误判
            vstatus = VerificationStatus.INCONCLUSIVE
            summary = f"INCONCLUSIVE: 未预期的执行状态 {cmd_result.status.value}"

        # 只有 FAILED 才提取 failure_signature（RepairLoop 的输入）
        signature = None
        if vstatus is VerificationStatus.FAILED:
            signature = extract_failure_signature(
                cmd_result.stdout, cmd_result.stderr
            )

        return VerificationResult(
            verification_id=request.verification_id,
            status=vstatus,
            exit_code=cmd_result.exit_code,
            duration_ms=cmd_result.duration_ms,
            stdout=cmd_result.stdout,
            stderr=cmd_result.stderr,
            stdout_truncated=cmd_result.stdout_truncated,
            stderr_truncated=cmd_result.stderr_truncated,
            failure_signature=signature,
            summary=summary,
        )