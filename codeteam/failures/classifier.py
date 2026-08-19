"""
ErrorClassifier: 把底层失败规范化为 AgentFailure。

设计原则（DD-W4-D3-01）：
- deterministic：不调用 LLM 分类，不依赖模型输出
- stage 敏感：同一个 TimeoutError 在不同 stage 映射不同 code
- 只分类：不 sleep、不 retry、不修改任何状态
"""
from __future__ import annotations

from typing import ClassVar

from codeteam.execution.models import (
    ApprovalDecision,
    CommandStatus,
    PolicyDecision,
)
from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.git.models import PatchResult, PatchStatus
from codeteam.sandbox.errors import SandboxError, SandboxMountError
from codeteam.verification.models import VerificationStatus


class ErrorClassifier:
    """确定性错误分类器。

    用法：
        classifier = ErrorClassifier()
        failure = classifier.classify(
            error=some_exception,
            stage=FailureStage.MODEL_CALL,
            operation="plan_generation",
            task_id="task-1",
            attempt=1,
        )
    """

    # code → (category, transient, retryable, recovery_action)
    # 注意：SECURITY 类全部 retryable=False（I1/I2/I3 的语义源头）
    _SIGNALS: ClassVar[dict[AgentErrorCode, tuple[ErrorCategory, bool, bool, RecoveryAction]]] = {
        # MODEL
        AgentErrorCode.MODEL_RATE_LIMIT: (ErrorCategory.MODEL, True, True, RecoveryAction.RETRY),
        AgentErrorCode.MODEL_OVERLOADED: (ErrorCategory.MODEL, True, True, RecoveryAction.RETRY),
        AgentErrorCode.MODEL_TIMEOUT: (ErrorCategory.MODEL, True, True, RecoveryAction.RETRY),
        AgentErrorCode.MODEL_AUTH_FAILED: (ErrorCategory.MODEL, False, False, RecoveryAction.STOP),
        AgentErrorCode.MODEL_QUOTA_EXCEEDED: (ErrorCategory.MODEL, False, False, RecoveryAction.STOP),
        AgentErrorCode.MODEL_INVALID_REQUEST: (ErrorCategory.MODEL, False, False, RecoveryAction.STOP),
        # CONTEXT
        AgentErrorCode.CONTEXT_INSUFFICIENT: (ErrorCategory.CONTEXT, False, False, RecoveryAction.RETRIEVE_MORE_CONTEXT),
        AgentErrorCode.CONTEXT_STALE: (ErrorCategory.CONTEXT, False, False, RecoveryAction.REREAD_AND_REGENERATE),
        AgentErrorCode.CONTEXT_BUDGET_EXCEEDED: (ErrorCategory.CONTEXT, False, False, RecoveryAction.COMPACT_CONTEXT),
        # PATCH
        AgentErrorCode.PATCH_INVALID: (ErrorCategory.PATCH, False, False, RecoveryAction.REREAD_AND_REGENERATE),
        AgentErrorCode.PATCH_CONTEXT_MISMATCH: (ErrorCategory.PATCH, False, False, RecoveryAction.REREAD_AND_REGENERATE),
        AgentErrorCode.PATCH_PATH_REJECTED: (ErrorCategory.PATCH, False, False, RecoveryAction.STOP),
        AgentErrorCode.PATCH_APPLY_FAILED: (ErrorCategory.PATCH, False, False, RecoveryAction.REREAD_AND_REGENERATE),
        # TOOL
        AgentErrorCode.TOOL_NOT_FOUND: (ErrorCategory.TOOL, False, False, RecoveryAction.STOP),
        AgentErrorCode.TOOL_TIMEOUT: (ErrorCategory.TOOL, True, False, RecoveryAction.STOP),
        AgentErrorCode.TOOL_EXECUTION_FAILED: (ErrorCategory.TOOL, False, False, RecoveryAction.STOP),
        # SECURITY —— 全部不可自动重试
        AgentErrorCode.POLICY_DENIED: (ErrorCategory.SECURITY, False, False, RecoveryAction.STOP),
        AgentErrorCode.APPROVAL_DENIED: (ErrorCategory.SECURITY, False, False, RecoveryAction.STOP),
        AgentErrorCode.SANDBOX_UNAVAILABLE: (ErrorCategory.SECURITY, False, False, RecoveryAction.STOP),
        AgentErrorCode.SANDBOX_VIOLATION: (ErrorCategory.SECURITY, False, False, RecoveryAction.STOP),
        # TEST
        AgentErrorCode.TEST_FAILED: (ErrorCategory.TEST, False, False, RecoveryAction.REPAIR),
        AgentErrorCode.TEST_TIMEOUT: (ErrorCategory.TEST, False, False, RecoveryAction.REPAIR),
        AgentErrorCode.TEST_FLAKY: (ErrorCategory.TEST, False, True, RecoveryAction.RETRY),
        # GIT / SESSION —— 第一版统一 STOP（day3 §七十八/七十九）
        AgentErrorCode.GIT_WORKTREE_CONFLICT: (ErrorCategory.GIT, False, False, RecoveryAction.STOP),
        AgentErrorCode.GIT_DIRTY_STATE: (ErrorCategory.GIT, False, False, RecoveryAction.STOP),
        AgentErrorCode.GIT_BASE_CHANGED: (ErrorCategory.GIT, False, False, RecoveryAction.STOP),
        AgentErrorCode.SESSION_NOT_FOUND: (ErrorCategory.SESSION, False, False, RecoveryAction.STOP),
        AgentErrorCode.SESSION_CORRUPTED: (ErrorCategory.SESSION, False, False, RecoveryAction.STOP),
        AgentErrorCode.SESSION_WORKTREE_MISSING: (ErrorCategory.SESSION, False, False, RecoveryAction.STOP),
        # USER
        AgentErrorCode.USER_INTERRUPT: (ErrorCategory.USER_INTERRUPT, False, False, RecoveryAction.PAUSE),
        # UNKNOWN —— fail closed（day3 §一百一十六）
        AgentErrorCode.UNKNOWN: (ErrorCategory.TOOL, False, False, RecoveryAction.STOP),
    }

    # code → 用户可见安全消息（模板固定，不含任何原始异常文本 → T18 secret-safe）
    _MESSAGES: ClassVar[dict[AgentErrorCode, str]] = {
        AgentErrorCode.MODEL_RATE_LIMIT: "模型服务请求过于频繁，正在等待后重试。",
        AgentErrorCode.MODEL_OVERLOADED: "模型服务暂时繁忙，正在重试。",
        AgentErrorCode.MODEL_TIMEOUT: "模型请求超时，正在重试。",
        AgentErrorCode.MODEL_AUTH_FAILED: "模型服务认证失败，请检查 API 配置。",
        AgentErrorCode.MODEL_QUOTA_EXCEEDED: "模型额度已用尽，请检查账户配置。",
        AgentErrorCode.MODEL_INVALID_REQUEST: "模型请求无效，无法继续。",
        AgentErrorCode.CONTEXT_INSUFFICIENT: "上下文信息不足，正在检索更多相关文件。",
        AgentErrorCode.CONTEXT_STALE: "上下文已过期，正在重新读取。",
        AgentErrorCode.CONTEXT_BUDGET_EXCEEDED: "上下文超出预算，正在压缩后重试。",
        AgentErrorCode.PATCH_INVALID: "生成的补丁无效，正在重新生成。",
        AgentErrorCode.PATCH_CONTEXT_MISMATCH: "文件已变化，正在重新读取后生成补丁。",
        AgentErrorCode.PATCH_PATH_REJECTED: "补丁包含不允许的路径，已终止。",
        AgentErrorCode.PATCH_APPLY_FAILED: "补丁应用失败，正在重新生成。",
        AgentErrorCode.TOOL_NOT_FOUND: "所需工具不存在，请检查环境配置。",
        AgentErrorCode.TOOL_TIMEOUT: "工具执行超时，已终止。",
        AgentErrorCode.TOOL_EXECUTION_FAILED: "工具执行失败，已终止。",
        AgentErrorCode.POLICY_DENIED: "该操作被安全策略拒绝，已终止。",
        AgentErrorCode.APPROVAL_DENIED: "该操作被用户拒绝，已终止。",
        AgentErrorCode.SANDBOX_UNAVAILABLE: "沙箱环境不可用，已安全终止。",
        AgentErrorCode.SANDBOX_VIOLATION: "检测到沙箱约束违反，已终止。",
        AgentErrorCode.TEST_FAILED: "测试未通过，正在分析并修复。",
        AgentErrorCode.TEST_TIMEOUT: "测试执行超时，正在分析修复。",
        AgentErrorCode.TEST_FLAKY: "测试疑似不稳定，正在受控重跑。",
        AgentErrorCode.GIT_WORKTREE_CONFLICT: "工作树冲突，已终止。",
        AgentErrorCode.GIT_DIRTY_STATE: "工作区状态异常，已终止。",
        AgentErrorCode.GIT_BASE_CHANGED: "基线分支已变化，已终止。",
        AgentErrorCode.SESSION_NOT_FOUND: "会话不存在，已终止。",
        AgentErrorCode.SESSION_CORRUPTED: "会话数据损坏，已终止。",
        AgentErrorCode.SESSION_WORKTREE_MISSING: "会话工作树丢失，已终止。",
        AgentErrorCode.USER_INTERRUPT: "用户中断了执行。",
        AgentErrorCode.UNKNOWN: "发生未知错误，已安全终止。",
    }

    # 消息关键词 → code 的 stage 级映射（day3 §六十九~八十 的 50 Case 覆盖）。
    # 元组顺序即优先级：先命中先返回。
    _STAGE_MESSAGE_MAP: ClassVar[
        dict[FailureStage, tuple[tuple[tuple[str, ...], AgentErrorCode], ...]]
    ] = {
        FailureStage.CONTEXT_RETRIEVAL: (
            (("stale", "expired", "changed"), AgentErrorCode.CONTEXT_STALE),
            (("budget", "overflow", "exceed", "too many"), AgentErrorCode.CONTEXT_BUDGET_EXCEEDED),
            (("insufficient", "not enough", "missing", "empty"), AgentErrorCode.CONTEXT_INSUFFICIENT),
        ),
        FailureStage.PATCH_VALIDATION: (
            (("syntax", "invalid", "malformed", "binary", "too many"), AgentErrorCode.PATCH_INVALID),
            (("does not apply", "mismatch", "context"), AgentErrorCode.PATCH_CONTEXT_MISMATCH),
            (("path", "forbidden", "outside"), AgentErrorCode.PATCH_PATH_REJECTED),
            (("apply",), AgentErrorCode.PATCH_APPLY_FAILED),
        ),
        FailureStage.PATCH_APPLY: (
            (("syntax", "invalid", "malformed", "binary", "too many"), AgentErrorCode.PATCH_INVALID),
            (("does not apply", "mismatch", "context"), AgentErrorCode.PATCH_CONTEXT_MISMATCH),
            (("path", "forbidden", "outside"), AgentErrorCode.PATCH_PATH_REJECTED),
            (("apply",), AgentErrorCode.PATCH_APPLY_FAILED),
        ),
        FailureStage.COMMAND_EXECUTION: (
            (("not found", "no such file", "executable"), AgentErrorCode.TOOL_NOT_FOUND),
            (("permission",), AgentErrorCode.TOOL_EXECUTION_FAILED),
            (("exit", "nonzero", "return code", "malformed"), AgentErrorCode.TOOL_EXECUTION_FAILED),
        ),
        FailureStage.VERIFICATION: (
            (("flaky",), AgentErrorCode.TEST_FLAKY),
        ),
        FailureStage.APPROVAL: (
            # 审批过期/跨任务授权 ≈ 无有效授权 → 按拒绝处理（Fail Closed）
            (("expired", "cross-task", "revoked"), AgentErrorCode.APPROVAL_DENIED),
        ),
        FailureStage.GIT: (
            (("conflict", "checked out"), AgentErrorCode.GIT_WORKTREE_CONFLICT),
            (("dirty",), AgentErrorCode.GIT_DIRTY_STATE),
            (("base", "sha"), AgentErrorCode.GIT_BASE_CHANGED),
        ),
        FailureStage.SESSION: (
            (("not found",), AgentErrorCode.SESSION_NOT_FOUND),
            (("worktree",), AgentErrorCode.SESSION_WORKTREE_MISSING),
            (("corrupted", "checkpoint"), AgentErrorCode.SESSION_CORRUPTED),
        ),
    }

    # ── 主入口 ───────────────────────────────────────────────

    def classify(
        self,
        *,
        error: object,
        stage: FailureStage,
        operation: str,
        task_id: str,
        attempt: int = 1,
        session_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AgentFailure:
        """把底层失败分类为 AgentFailure。

        检测顺序（从最具体到最兜底）：
        ① KeyboardInterrupt → USER_INTERRUPT（BaseException，不是 Exception）
        ② ApprovalDecision.DENIED → APPROVAL_DENIED
        ③ PolicyDecision.DENY / CommandStatus.POLICY_DENIED → POLICY_DENIED
        ④ SandboxError 家族 → SANDBOX_UNAVAILABLE
        ⑤ VerificationStatus（stage=VERIFICATION）→ TEST_*
        ⑥ PatchResult（stage=PATCH_*）→ PATCH_*
        ⑦ stage=MODEL_CALL → 按 status_code/异常类型/消息
        ⑧ 兜底 → UNKNOWN（fail closed）
        """
        merged = dict(metadata or {})

        # ① 用户中断（必须最先——KeyboardInterrupt 不是 Exception 子类）
        if isinstance(error, KeyboardInterrupt):
            return self._build(
                AgentErrorCode.USER_INTERRUPT, stage, operation,
                task_id, attempt, session_id, merged, error,
            )

        # ② 用户拒绝审批
        if isinstance(error, ApprovalDecision):
            if error == ApprovalDecision.DENIED:
                return self._build(
                    AgentErrorCode.APPROVAL_DENIED, stage, operation,
                    task_id, attempt, session_id, merged, error,
                )
            # APPROVED 不是错误——调用方不应传进来，兜底为 UNKNOWN
            return self._build(AgentErrorCode.UNKNOWN, stage, operation, task_id, attempt, session_id, merged, error)

        # ③ 策略拒绝（两种来源：PolicyDecision 枚举 或 CommandStatus 字符串）
        if isinstance(error, PolicyDecision) and error == PolicyDecision.DENY:
            return self._build(AgentErrorCode.POLICY_DENIED, stage, operation, task_id, attempt, session_id, merged, error)
        if error == CommandStatus.POLICY_DENIED.value or error == CommandStatus.POLICY_DENIED:
            return self._build(AgentErrorCode.POLICY_DENIED, stage, operation, task_id, attempt, session_id, merged, error)

        # ④ 沙箱错误（继承链一次覆盖整个家族）
        #    Mount 配置不合法 → 违规；其余（daemon 不可用等）→ 不可用
        if isinstance(error, SandboxError):
            if isinstance(error, SandboxMountError):
                code = AgentErrorCode.SANDBOX_VIOLATION
            else:
                code = AgentErrorCode.SANDBOX_UNAVAILABLE
            return self._build(code, stage, operation, task_id, attempt, session_id, merged, error)

        # ⑤ 验证结果（stage 必须是 VERIFICATION）
        if isinstance(error, VerificationStatus):
            if error == VerificationStatus.FAILED:
                code = AgentErrorCode.TEST_FAILED
            elif error == VerificationStatus.TIMED_OUT:
                code = AgentErrorCode.TEST_TIMEOUT
            elif error == VerificationStatus.START_FAILED:
                # pytest 可执行文件缺失 → 工具问题，不是测试问题（day3 §十）
                code = AgentErrorCode.TOOL_NOT_FOUND
            else:  # BLOCKED / INCONCLUSIVE → 保守 UNKNOWN
                code = AgentErrorCode.UNKNOWN
            return self._build(code, stage, operation, task_id, attempt, session_id, merged, error)

        # ⑥ Patch 结果
        if isinstance(error, PatchResult):
            if error.status == PatchStatus.SECURITY_REJECTED:
                code = AgentErrorCode.PATCH_PATH_REJECTED
            elif error.status == PatchStatus.CHECK_FAILED:
                # git apply --check 失败 ≈ 上下文失配（文件已变化）
                code = AgentErrorCode.PATCH_CONTEXT_MISMATCH
            elif error.status == PatchStatus.APPLY_FAILED:
                code = AgentErrorCode.PATCH_APPLY_FAILED
            else:  # VALID / APPLIED 不是错误
                code = AgentErrorCode.UNKNOWN
            if error.patch_sha256:
                merged["patch_sha256"] = error.patch_sha256
            return self._build(code, stage, operation, task_id, attempt, session_id, merged, error)

        # ⑦ 消息型 stage 分类（day3 §六十九~八十 的 50 Case 覆盖）
        if stage in self._STAGE_MESSAGE_MAP:
            code = self._match_stage_message(
                str(error).lower(), self._STAGE_MESSAGE_MAP[stage]
            )
            if code is not None:
                return self._build(code, stage, operation, task_id, attempt, session_id, merged, error)

        # ⑦b stage 级 Timeout 语义（§三十七）：
        #     VERIFICATION 超时 → 测试死循环 → REPAIR；COMMAND 超时 → 工具超时
        if stage == FailureStage.VERIFICATION and isinstance(error, TimeoutError):
            return self._build(AgentErrorCode.TEST_TIMEOUT, stage, operation, task_id, attempt, session_id, merged, error)
        if stage == FailureStage.COMMAND_EXECUTION and isinstance(error, TimeoutError):
            return self._build(AgentErrorCode.TOOL_TIMEOUT, stage, operation, task_id, attempt, session_id, merged, error)

        # ⑧ MODEL_CALL：按 HTTP 语义 / 异常类型 / 消息分类
        if stage == FailureStage.MODEL_CALL:
            return self._classify_model_call(error, stage, operation, task_id, attempt, session_id, merged)

        # ⑨ 兜底：UNKNOWN → fail closed
        return self._build(AgentErrorCode.UNKNOWN, stage, operation, task_id, attempt, session_id, merged, error)

    # ── 消息匹配辅助 ─────────────────────────────────────────

    @staticmethod
    def _match_stage_message(
        message: str,
        rules: tuple[tuple[tuple[str, ...], AgentErrorCode], ...],
    ) -> AgentErrorCode | None:
        """按关键词规则表匹配消息，返回第一个命中的 code。"""
        for keywords, code in rules:
            for keyword in keywords:
                if keyword in message:
                    return code
        return None

    # ── MODEL_CALL 专用分类 ──────────────────────────────────

    def _classify_model_call(self, error, stage, operation, task_id, attempt, session_id, merged):
        status_code = getattr(error, "status_code", None)
        message = str(error).lower()

        # 上下文溢出（day3 §七十一：即使来自模型 API，也归 CONTEXT 类）
        if "context length" in message or "maximum context" in message or "too many tokens" in message:
            return self._build(AgentErrorCode.CONTEXT_BUDGET_EXCEEDED, stage, operation, task_id, attempt, session_id, merged, error)

        if status_code == 429:
            # 提取 Retry-After 供 RetryPolicy 使用
            retry_after = getattr(error, "retry_after", None)
            if retry_after is not None:
                merged["retry_after"] = float(retry_after)
            return self._build(AgentErrorCode.MODEL_RATE_LIMIT, stage, operation, task_id, attempt, session_id, merged, error)

        if status_code in (500, 502, 503):
            return self._build(AgentErrorCode.MODEL_OVERLOADED, stage, operation, task_id, attempt, session_id, merged, error)

        if status_code in (401, 403):
            return self._build(AgentErrorCode.MODEL_AUTH_FAILED, stage, operation, task_id, attempt, session_id, merged, error)

        if status_code in (402, 429):
            return self._build(AgentErrorCode.MODEL_QUOTA_EXCEEDED, stage, operation, task_id, attempt, session_id, merged, error)

        if status_code == 400:
            return self._build(AgentErrorCode.MODEL_INVALID_REQUEST, stage, operation, task_id, attempt, session_id, merged, error)

        if isinstance(error, TimeoutError):
            return self._build(AgentErrorCode.MODEL_TIMEOUT, stage, operation, task_id, attempt, session_id, merged, error)

        if isinstance(error, (ConnectionError, OSError)):
            # 连接重置/断开 → 过载语义（transient + retryable）
            return self._build(AgentErrorCode.MODEL_OVERLOADED, stage, operation, task_id, attempt, session_id, merged, error)

        return self._build(AgentErrorCode.UNKNOWN, stage, operation, task_id, attempt, session_id, merged, error)

    # ── 构建辅助 ─────────────────────────────────────────────

    def _build(
        self,
        code: AgentErrorCode,
        stage: FailureStage,
        operation: str,
        task_id: str,
        attempt: int,
        session_id: str | None,
        metadata: dict[str, object],
        error: object,
    ) -> AgentFailure:
        category, transient, retryable, action = self._SIGNALS[code]
        if operation:
            metadata["operation"] = operation

        return AgentFailure(
            failure_id=f"{task_id}:{stage.value}:{code.value}:{attempt}",
            task_id=task_id,
            session_id=session_id,
            category=category,
            code=code,
            stage=stage,
            message=self._MESSAGES.get(code, "发生错误。"),
            transient=transient,
            retryable=retryable,
            attempt=attempt,
            recommended_recovery=action,
            source_type=type(error).__name__ if error is not None else None,
            source_message=str(error) if error is not None else None,
            cause=error,
            metadata=metadata,
        )