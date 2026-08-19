"""tests/failures/fault_cases.py — 50 Case Fault Injection Corpus。

这是 day3.md §六十七~六十九 定义的 50 条故障注入数据：
- 数据驱动的分类正确性测试的数据源（test_fault_injection.py）
- 周度评测脚本直接 import 的数据出口（FailureCase 含
  case_id/stage/raw_error/expected_category/expected_code/
  expected_action/expected_retryable 六字段）

分布（按 case_id 前缀，day3 §六十九）：
    M(MODEL)=10  C(CONTEXT)=6  P(PATCH)=7  T(TOOL)=6  S(SECURITY)=6
    V(TEST)=5    G(GIT)=4      N(SESSION)=4  U(INTERRUPT)=2
    合计 50

expected_* 来源：day3.md §七十~八十 的规格表（冻结于代码之前，
不是"按当前实现回填"——实现已按规格补齐 stage 级消息分类）。
"""

from __future__ import annotations

from dataclasses import dataclass

from codeteam.execution.models import ApprovalDecision, PolicyDecision
from codeteam.failures.models import (
    AgentErrorCode,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.git.models import PatchResult, PatchStatus
from codeteam.sandbox.errors import DockerUnavailableError, SandboxMountError
from codeteam.verification.models import VerificationStatus


@dataclass(frozen=True)
class FailureCase:
    """一条故障注入案例。

    周度评测脚本 import 本模块后遍历 FAILURE_CASES，
    断言 expected_* 与实际分类一致——脚本只读不重复测量。
    """

    case_id: str
    stage: FailureStage
    raw_error: object
    expected_category: ErrorCategory
    expected_code: AgentErrorCode
    expected_action: RecoveryAction
    expected_retryable: bool


class _FakeStatusError(Exception):
    """带 status_code 的假传输异常（MODEL 分类输入）。"""

    def __init__(self, message: str, status_code: int, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


# Patch 结构化输入（classifier 只读，可安全共享）
_PATCH_CHECK_FAILED = PatchResult(
    status=PatchStatus.CHECK_FAILED,
    patch_sha256="sha-check-failed",
    affected_paths=["src/auth/service.py"],
)
_PATCH_SECURITY_REJECTED = PatchResult(
    status=PatchStatus.SECURITY_REJECTED,
    patch_sha256="sha-security",
    affected_paths=["/etc/passwd"],
)
_PATCH_APPLY_FAILED = PatchResult(
    status=PatchStatus.APPLY_FAILED,
    patch_sha256="sha-apply-failed",
    affected_paths=["src/auth/service.py"],
)

FAILURE_CASES: list[FailureCase] = [
    # ── MODEL 10 ─────────────────────────────────────────────
    FailureCase("M01", FailureStage.MODEL_CALL,
                _FakeStatusError("temporary rate limit", 429),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_RATE_LIMIT,
                RecoveryAction.RETRY, True),
    FailureCase("M02", FailureStage.MODEL_CALL,
                _FakeStatusError("rate limit", 429, retry_after=3.0),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_RATE_LIMIT,
                RecoveryAction.RETRY, True),
    FailureCase("M03", FailureStage.MODEL_CALL,
                _FakeStatusError("provider overloaded", 503),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_OVERLOADED,
                RecoveryAction.RETRY, True),
    FailureCase("M04", FailureStage.MODEL_CALL,
                TimeoutError("model call timed out"),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_TIMEOUT,
                RecoveryAction.RETRY, True),
    FailureCase("M05", FailureStage.MODEL_CALL,
                ConnectionError("connection reset by peer"),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_OVERLOADED,
                RecoveryAction.RETRY, True),
    FailureCase("M06", FailureStage.MODEL_CALL,
                _FakeStatusError("invalid api key", 401),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_AUTH_FAILED,
                RecoveryAction.STOP, False),
    FailureCase("M07", FailureStage.MODEL_CALL,
                _FakeStatusError("quota exceeded", 402),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_QUOTA_EXCEEDED,
                RecoveryAction.STOP, False),
    FailureCase("M08", FailureStage.MODEL_CALL,
                _FakeStatusError("invalid model name", 400),
                ErrorCategory.MODEL, AgentErrorCode.MODEL_INVALID_REQUEST,
                RecoveryAction.STOP, False),
    FailureCase("M09", FailureStage.MODEL_CALL,
                _FakeStatusError("maximum context length exceeded", 400),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_BUDGET_EXCEEDED,
                RecoveryAction.COMPACT_CONTEXT, False),
    FailureCase("M10", FailureStage.MODEL_CALL,
                ValueError("malformed provider response"),
                ErrorCategory.TOOL, AgentErrorCode.UNKNOWN,
                RecoveryAction.STOP, False),

    # ── CONTEXT 6 ────────────────────────────────────────────
    FailureCase("C01", FailureStage.CONTEXT_RETRIEVAL,
                RuntimeError("token budget exceeded"),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_BUDGET_EXCEEDED,
                RecoveryAction.COMPACT_CONTEXT, False),
    FailureCase("C02", FailureStage.CONTEXT_RETRIEVAL,
                RuntimeError("insufficient relevant files"),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_INSUFFICIENT,
                RecoveryAction.RETRIEVE_MORE_CONTEXT, False),
    FailureCase("C03", FailureStage.CONTEXT_RETRIEVAL,
                RuntimeError("stale file content"),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_STALE,
                RecoveryAction.REREAD_AND_REGENERATE, False),
    FailureCase("C04", FailureStage.CONTEXT_RETRIEVAL,
                RuntimeError("important symbol missing"),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_INSUFFICIENT,
                RecoveryAction.RETRIEVE_MORE_CONTEXT, False),
    FailureCase("C05", FailureStage.CONTEXT_RETRIEVAL,
                RuntimeError("compact summary missing constraint"),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_INSUFFICIENT,
                RecoveryAction.RETRIEVE_MORE_CONTEXT, False),
    FailureCase("C06", FailureStage.MODEL_CALL,
                _FakeStatusError("too many tokens in context", 400),
                ErrorCategory.CONTEXT, AgentErrorCode.CONTEXT_BUDGET_EXCEEDED,
                RecoveryAction.COMPACT_CONTEXT, False),

    # ── PATCH 7 ──────────────────────────────────────────────
    FailureCase("P01", FailureStage.PATCH_VALIDATION,
                RuntimeError("patch syntax invalid"),
                ErrorCategory.PATCH, AgentErrorCode.PATCH_INVALID,
                RecoveryAction.REREAD_AND_REGENERATE, False),
    FailureCase("P02", FailureStage.PATCH_APPLY,
                _PATCH_CHECK_FAILED,
                ErrorCategory.PATCH, AgentErrorCode.PATCH_CONTEXT_MISMATCH,
                RecoveryAction.REREAD_AND_REGENERATE, False),
    FailureCase("P03", FailureStage.PATCH_VALIDATION,
                _PATCH_SECURITY_REJECTED,
                ErrorCategory.PATCH, AgentErrorCode.PATCH_PATH_REJECTED,
                RecoveryAction.STOP, False),
    FailureCase("P04", FailureStage.PATCH_VALIDATION,
                RuntimeError("absolute path outside workspace"),
                ErrorCategory.PATCH, AgentErrorCode.PATCH_PATH_REJECTED,
                RecoveryAction.STOP, False),
    FailureCase("P05", FailureStage.PATCH_VALIDATION,
                RuntimeError("binary patch rejected"),
                ErrorCategory.PATCH, AgentErrorCode.PATCH_INVALID,
                RecoveryAction.REREAD_AND_REGENERATE, False),
    FailureCase("P06", FailureStage.PATCH_VALIDATION,
                RuntimeError("too many files in patch"),
                ErrorCategory.PATCH, AgentErrorCode.PATCH_INVALID,
                RecoveryAction.REREAD_AND_REGENERATE, False),
    FailureCase("P07", FailureStage.PATCH_APPLY,
                _PATCH_APPLY_FAILED,
                ErrorCategory.PATCH, AgentErrorCode.PATCH_APPLY_FAILED,
                RecoveryAction.REREAD_AND_REGENERATE, False),

    # ── TOOL 6 ───────────────────────────────────────────────
    FailureCase("T01", FailureStage.COMMAND_EXECUTION,
                RuntimeError("pytest executable not found"),
                ErrorCategory.TOOL, AgentErrorCode.TOOL_NOT_FOUND,
                RecoveryAction.STOP, False),
    FailureCase("T02", FailureStage.COMMAND_EXECUTION,
                RuntimeError("permission denied starting process"),
                ErrorCategory.TOOL, AgentErrorCode.TOOL_EXECUTION_FAILED,
                RecoveryAction.STOP, False),
    FailureCase("T03", FailureStage.COMMAND_EXECUTION,
                TimeoutError("command timed out"),
                ErrorCategory.TOOL, AgentErrorCode.TOOL_TIMEOUT,
                RecoveryAction.STOP, False),
    FailureCase("T04", FailureStage.COMMAND_EXECUTION,
                RuntimeError("command exited with nonzero exit code 1"),
                ErrorCategory.TOOL, AgentErrorCode.TOOL_EXECUTION_FAILED,
                RecoveryAction.STOP, False),
    FailureCase("T05", FailureStage.COMMAND_EXECUTION,
                RuntimeError("malformed tool result"),
                ErrorCategory.TOOL, AgentErrorCode.TOOL_EXECUTION_FAILED,
                RecoveryAction.STOP, False),
    FailureCase("T06", FailureStage.SANDBOX,
                DockerUnavailableError("docker daemon down"),
                ErrorCategory.SECURITY, AgentErrorCode.SANDBOX_UNAVAILABLE,
                RecoveryAction.STOP, False),

    # ── SECURITY 6 ───────────────────────────────────────────
    FailureCase("S01", FailureStage.COMMAND_EXECUTION,
                PolicyDecision.DENY,
                ErrorCategory.SECURITY, AgentErrorCode.POLICY_DENIED,
                RecoveryAction.STOP, False),
    FailureCase("S02", FailureStage.APPROVAL,
                ApprovalDecision.DENIED,
                ErrorCategory.SECURITY, AgentErrorCode.APPROVAL_DENIED,
                RecoveryAction.STOP, False),
    FailureCase("S03", FailureStage.APPROVAL,
                RuntimeError("approval expired"),
                ErrorCategory.SECURITY, AgentErrorCode.APPROVAL_DENIED,
                RecoveryAction.STOP, False),
    FailureCase("S04", FailureStage.APPROVAL,
                RuntimeError("cross-task grant attempt"),
                ErrorCategory.SECURITY, AgentErrorCode.APPROVAL_DENIED,
                RecoveryAction.STOP, False),
    FailureCase("S05", FailureStage.SANDBOX,
                DockerUnavailableError("docker CLI missing"),
                ErrorCategory.SECURITY, AgentErrorCode.SANDBOX_UNAVAILABLE,
                RecoveryAction.STOP, False),
    FailureCase("S06", FailureStage.SANDBOX,
                SandboxMountError("mount config unsafe"),
                ErrorCategory.SECURITY, AgentErrorCode.SANDBOX_VIOLATION,
                RecoveryAction.STOP, False),

    # ── TEST 5 ───────────────────────────────────────────────
    FailureCase("V01", FailureStage.VERIFICATION,
                VerificationStatus.FAILED,
                ErrorCategory.TEST, AgentErrorCode.TEST_FAILED,
                RecoveryAction.REPAIR, False),
    FailureCase("V02", FailureStage.VERIFICATION,
                VerificationStatus.FAILED,  # 回归失败：结构化信号同为 FAILED
                ErrorCategory.TEST, AgentErrorCode.TEST_FAILED,
                RecoveryAction.REPAIR, False),
    FailureCase("V03", FailureStage.VERIFICATION,
                VerificationStatus.TIMED_OUT,
                ErrorCategory.TEST, AgentErrorCode.TEST_TIMEOUT,
                RecoveryAction.REPAIR, False),
    FailureCase("V04", FailureStage.VERIFICATION,
                RuntimeError("test flaky suspected"),
                ErrorCategory.TEST, AgentErrorCode.TEST_FLAKY,
                RecoveryAction.RETRY, True),
    FailureCase("V05", FailureStage.VERIFICATION,
                VerificationStatus.INCONCLUSIVE,
                ErrorCategory.TOOL, AgentErrorCode.UNKNOWN,
                RecoveryAction.STOP, False),

    # ── GIT 4 ────────────────────────────────────────────────
    FailureCase("G01", FailureStage.GIT,
                RuntimeError("worktree conflict detected"),
                ErrorCategory.GIT, AgentErrorCode.GIT_WORKTREE_CONFLICT,
                RecoveryAction.STOP, False),
    FailureCase("G02", FailureStage.GIT,
                RuntimeError("branch already checked out"),
                ErrorCategory.GIT, AgentErrorCode.GIT_WORKTREE_CONFLICT,
                RecoveryAction.STOP, False),
    FailureCase("G03", FailureStage.GIT,
                RuntimeError("dirty worktree removal refused"),
                ErrorCategory.GIT, AgentErrorCode.GIT_DIRTY_STATE,
                RecoveryAction.STOP, False),
    FailureCase("G04", FailureStage.GIT,
                RuntimeError("base sha missing"),
                ErrorCategory.GIT, AgentErrorCode.GIT_BASE_CHANGED,
                RecoveryAction.STOP, False),

    # ── SESSION 4 ────────────────────────────────────────────
    FailureCase("N01", FailureStage.SESSION,
                RuntimeError("session not found"),
                ErrorCategory.SESSION, AgentErrorCode.SESSION_NOT_FOUND,
                RecoveryAction.STOP, False),
    FailureCase("N02", FailureStage.SESSION,
                RuntimeError("session manifest corrupted"),
                ErrorCategory.SESSION, AgentErrorCode.SESSION_CORRUPTED,
                RecoveryAction.STOP, False),
    FailureCase("N03", FailureStage.SESSION,
                RuntimeError("session worktree missing"),
                ErrorCategory.SESSION, AgentErrorCode.SESSION_WORKTREE_MISSING,
                RecoveryAction.STOP, False),
    FailureCase("N04", FailureStage.SESSION,
                RuntimeError("checkpoint missing"),
                ErrorCategory.SESSION, AgentErrorCode.SESSION_CORRUPTED,
                RecoveryAction.STOP, False),

    # ── INTERRUPT 2 ──────────────────────────────────────────
    FailureCase("U01", FailureStage.MODEL_CALL,
                KeyboardInterrupt(),
                ErrorCategory.USER_INTERRUPT, AgentErrorCode.USER_INTERRUPT,
                RecoveryAction.PAUSE, False),
    FailureCase("U02", FailureStage.PLANNING,
                KeyboardInterrupt(),
                ErrorCategory.USER_INTERRUPT, AgentErrorCode.USER_INTERRUPT,
                RecoveryAction.PAUSE, False),
]
