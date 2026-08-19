"""
codeteam.failures.models - Agent Runtime 错误分类与恢复的 Domain 模型

与 codeteam/errors.py（Week1 传输层）的关系：
- errors.py 是 Provider/HTTP 传输层分类（RATE_LIMIT/TIMEOUT/AUTH...）
- 本文件是 Agent Runtime 业务语义层分类（MODEL/PATCH/TEST/SECURITY...）
- 两者职责不同，互不替代。DD-W4-D3-01 中论证该分层。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ErrorCategory(str, Enum):
    """错误大类：便于统计。

    保持粗粒度——真正的行为差异放在 AgentErrorCode。
    """
    MODEL = "model"                # 模型调用相关失败
    CONTEXT = "context"            # 上下文获取/预算相关失败
    PATCH = "patch"                # Patch 生成/校验/应用失败
    TOOL = "tool"                  # 工具执行失败
    SECURITY = "security"          # 安全策略/审批/沙箱失败
    TEST = "test"                  # 测试验证失败
    GIT = "git"                    # Git 操作失败
    SESSION = "session"            # 会话状态失败
    USER_INTERRUPT = "user_interrupt"  # 用户主动中断


class AgentErrorCode(str, Enum):
    """具体错误码：决定恢复策略。

    Code 足以区分"下一步行为明显不同"的 Failure。
    """

    # ── MODEL ──
    MODEL_RATE_LIMIT = "model_rate_limit"        # 429 限流，Retry-After 可用
    MODEL_OVERLOADED = "model_overloaded"        # 503 过载，稍后重试
    MODEL_TIMEOUT = "model_timeout"              # 请求超时（transient）
    MODEL_AUTH_FAILED = "model_auth_failed"      # API Key 无效——永久
    MODEL_CONTEXT_OVERFLOW = "model_context_overflow"  # Provider 报告上下文超限
    MODEL_INVALID_REQUEST = "model_invalid_request"    # 请求格式错误——永久
    MODEL_QUOTA_EXCEEDED = "model_quota_exceeded"      # Provider 配额超限——永久

    # ── CONTEXT ──
    CONTEXT_INSUFFICIENT = "context_insufficient"      # 相关文件不足
    CONTEXT_STALE = "context_stale"                    # 文件内容已过期
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded" # 自身预算超限

    # ── PATCH ──
    PATCH_INVALID = "patch_invalid"                # 语法/格式非法
    PATCH_CONTEXT_MISMATCH = "patch_context_mismatch"  # 上下文版本失配
    PATCH_PATH_REJECTED = "patch_path_rejected"    # 路径不被允许（含越界）
    PATCH_APPLY_FAILED = "patch_apply_failed"      # git apply 失败

    # ── TOOL ──
    TOOL_NOT_FOUND = "tool_not_found"              # 可执行文件不存在
    TOOL_TIMEOUT = "tool_timeout"                  # 进程超时
    TOOL_EXECUTION_FAILED = "tool_execution_failed" # 非零退出等执行失败

    # ── SECURITY ──
    POLICY_DENIED = "policy_denied"                # Runtime 策略拒绝
    APPROVAL_DENIED = "approval_denied"            # 用户明确拒绝
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"    # Docker 不可用
    SANDBOX_VIOLATION = "sandbox_violation"        # 沙箱约束被违反

    # ── TEST ──
    TEST_FAILED = "test_failed"                    # 断言失败
    TEST_TIMEOUT = "test_timeout"                  # 测试超时（可能死循环）
    TEST_FLAKY = "test_flaky"                      # 疑似不稳定测试

    # ── GIT ──
    GIT_WORKTREE_CONFLICT = "git_worktree_conflict"
    GIT_DIRTY_STATE = "git_dirty_state"
    GIT_BASE_CHANGED = "git_base_changed"

    # ── SESSION ──
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_CORRUPTED = "session_corrupted"
    SESSION_WORKTREE_MISSING = "session_worktree_missing"

    # ── USER ──
    USER_INTERRUPT = "user_interrupt"              # Ctrl+C / Esc
    UNKNOWN = "unknown"                            # 无法识别 - fail closed


class FailureStage(str, Enum):
    """失败发生的生命周期阶段。

    同一个 Exception 在不同 Stage 映射成不同 AgentFailure——
    这是 Classifier 的第二个关键输入。
    """
    PLANNING = "planning"
    CONTEXT_RETRIEVAL = "context_retrieval"
    MODEL_CALL = "model_call"
    PATCH_VALIDATION = "patch_validation"
    PATCH_APPLY = "patch_apply"
    COMMAND_EXECUTION = "command_execution"
    VERIFICATION = "verification"
    APPROVAL = "approval"
    SANDBOX = "sandbox"
    GIT = "git"
    SESSION = "session"


class RecoveryAction(str, Enum):
    """Runtime 下一步动作。

    只做决策标识——真正执行在 Orchestrator。
    """
    RETRY = "retry"                        # 再执行同一个动作（等待后）
    REREAD_AND_REGENERATE = "reread_and_regenerate"  # 重读文件+重新生成
    RETRIEVE_MORE_CONTEXT = "retrieve_more_context"  # 扩大上下文检索
    COMPACT_CONTEXT = "compact_context"    # 压缩上下文再试
    REPAIR = "repair"                      # 修改实现（Day2 RepairLoop）
    REPLAN = "replan"                      # 重新规划（Day1 planner.replan）
    ASK_USER = "ask_user"                  # 询问用户决策
    PAUSE = "pause"                        # 暂停（保留状态）
    STOP = "stop"                          # 终止（不可恢复）


class AgentFailure(BaseModel):
    """Agent Runtime 的语义化失败模型。

    契约要点：
    1. cause preservation（wrap not erase）：
       source_type / source_message / cause 保存原始异常，
       绝不只留一句 "model failed"。
    2. internal ≠ user-facing：
       message 是 sanitize 后的用户可见文本；
       原始诊断信息在 source_message / metadata 中。
    3. recommended_recovery 是"建议"（方案 B，day3 §四十九）：
       RecoveryPolicy 据此决策，真正执行在 Orchestrator。
    4. 不可变语义：一次失败的事实不应被修改。
       （Pydantic 下用 model_copy 生成新实例表示新状态）

    Attributes:
        failure_id: 失败唯一标识（如 "f-<task>-<attempt>-<uuid4hex>"）
        task_id: 所属任务
        session_id: 所属会话（Day 4 持久化用，第一版可为 None）
        category: 错误大类
        code: 具体错误码
        stage: 失败发生的生命周期阶段
        message: 用户可见消息（已 sanitize，不含密钥/路径细节）
        transient: 原因是否会随时间自然消失
        retryable: 重试同一动作是否有合理成功概率
        attempt: 该操作已尝试次数（1-based）
        recommended_recovery: 建议的恢复动作
        source_type: 原始异常类型名（如 "OpenAIRateLimitError"）
        source_message: 原始异常消息（内部诊断用，可能含敏感信息）
        cause: 原始异常对象（内存中传递；序列化时排除）
        metadata: 结构化诊断信息（status_code / retry_after / request_id...）
    """
    failure_id: str
    task_id: str
    session_id: str | None = None

    category: ErrorCategory
    code: AgentErrorCode
    stage: FailureStage

    message: str

    transient: bool
    retryable: bool

    attempt: int = 1

    recommended_recovery: RecoveryAction

    source_type: str | None = None
    source_message: str | None = None
    cause: object = Field(
        default=None,
        exclude=True,  # 序列化时排除原始异常对象
    )

    metadata: dict[str, object] = Field(default_factory=dict)

    def to_public_message(self) -> str:
        """返回面向用户的安全消息。

        与 message 相同——第一版 message 在构造时已 sanitize。
        单独方法的意义：未来如果 sanitize 逻辑复杂化，
        调用方（CLI / 事件）统一从这里取，不用猜哪个字段安全。
        """
        return self.message