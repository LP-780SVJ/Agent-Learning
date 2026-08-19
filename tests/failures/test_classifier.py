"""tests/failures/test_classifier.py — ErrorClassifier 单元测试。

对应 day3.md §九十 分层原则的 Classifier 单测层：
只断言「raw failure + stage → expected AgentFailure」，
不涉及 Orchestrator 行为。

覆盖：
- day3 §八十一~八十八 的 8 条 Required 映射
- §三十七 的 Timeout 三场景 stage 敏感性（核心用例）
- §十 的「同一 Exception 不同 stage 不同分类」设计原则
- operation/metadata 输入确实影响结果
- cause preservation（T17）与 secret-safe（T18）
"""

from __future__ import annotations

import pytest

from codeteam.execution.models import ApprovalDecision, PolicyDecision
from codeteam.failures.classifier import ErrorClassifier
from codeteam.failures.models import (
    AgentErrorCode,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.git.models import PatchResult, PatchStatus
from codeteam.sandbox.errors import DockerUnavailableError
from codeteam.verification.models import VerificationStatus


@pytest.fixture
def classifier() -> ErrorClassifier:
    return ErrorClassifier()


def _classify(classifier, error, stage, **kwargs):
    """统一起点：task_id='t1'，其余按需覆盖。"""
    defaults = {"task_id": "t1", "operation": "test_operation"}
    defaults.update(kwargs)
    return classifier.classify(error=error, stage=stage, **defaults)


class _FakeStatusError(Exception):
    """带 status_code 属性的假传输异常（MODEL 分类输入）。"""

    def __init__(self, message: str, status_code: int, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class TestRequiredMappings:
    """day3 §八十一~八十八 的 8 条 Required 映射。"""

    def test_rate_limit_maps_to_retry(self, classifier) -> None:
        """验收(rate limit→retry): 429 在 MODEL_CALL → MODEL_RATE_LIMIT，
        retryable=True，建议 RETRY——临时限流重试有合理成功概率。"""
        error = _FakeStatusError("rate limited", status_code=429)
        f = _classify(classifier, error, FailureStage.MODEL_CALL)
        assert f.category == ErrorCategory.MODEL
        assert f.code == AgentErrorCode.MODEL_RATE_LIMIT
        assert f.retryable is True
        assert f.transient is True
        assert f.recommended_recovery == RecoveryAction.RETRY

    def test_rate_limit_extracts_retry_after_into_metadata(self, classifier) -> None:
        """验收(Retry-After 提取): 429 的 retry_after 进入 metadata，
        供 RetryPolicy 读取（T16 的数据来源）。"""
        error = _FakeStatusError("rate limited", status_code=429, retry_after=2.5)
        f = _classify(classifier, error, FailureStage.MODEL_CALL)
        assert f.metadata["retry_after"] == 2.5

    def test_model_timeout_maps_to_retry(self, classifier) -> None:
        """验收(model timeout→retry): TimeoutError 在 MODEL_CALL →
        MODEL_TIMEOUT，retryable=True。"""
        f = _classify(classifier, TimeoutError("timed out"), FailureStage.MODEL_CALL)
        assert f.code == AgentErrorCode.MODEL_TIMEOUT
        assert f.retryable is True
        assert f.recommended_recovery == RecoveryAction.RETRY

    def test_patch_check_failed_maps_to_reread(self, classifier) -> None:
        """验收(patch mismatch→reread): PatchStatus.CHECK_FAILED →
        PATCH_CONTEXT_MISMATCH，retryable=False，建议 REREAD_AND_REGENERATE——
        同一个 Patch 重试必然失败（I4 语义源头）。"""
        result = PatchResult(
            status=PatchStatus.CHECK_FAILED,
            patch_sha256="abc123",
            affected_paths=["src/auth/service.py"],
        )
        f = _classify(classifier, result, FailureStage.PATCH_APPLY)
        assert f.code == AgentErrorCode.PATCH_CONTEXT_MISMATCH
        assert f.category == ErrorCategory.PATCH
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.REREAD_AND_REGENERATE

    def test_test_failed_maps_to_repair(self, classifier) -> None:
        """验收(test fail→repair): VerificationStatus.FAILED →
        TEST_FAILED，建议 REPAIR 而非盲目重跑测试（I5 语义源头）。"""
        f = _classify(classifier, VerificationStatus.FAILED, FailureStage.VERIFICATION)
        assert f.code == AgentErrorCode.TEST_FAILED
        assert f.recommended_recovery == RecoveryAction.REPAIR
        assert f.retryable is False

    def test_policy_denied_maps_to_stop(self, classifier) -> None:
        """验收(policy deny→stop): PolicyDecision.DENY →
        POLICY_DENIED，retryable=False，STOP——安全策略不可绕过（I1）。"""
        f = _classify(classifier, PolicyDecision.DENY, FailureStage.COMMAND_EXECUTION)
        assert f.code == AgentErrorCode.POLICY_DENIED
        assert f.category == ErrorCategory.SECURITY
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.STOP

    def test_approval_denied_maps_to_stop(self, classifier) -> None:
        """验收(approval deny→stop): ApprovalDecision.DENIED →
        APPROVAL_DENIED，STOP——用户决定不可忽略（I2）。"""
        f = _classify(classifier, ApprovalDecision.DENIED, FailureStage.APPROVAL)
        assert f.code == AgentErrorCode.APPROVAL_DENIED
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.STOP

    def test_sandbox_unavailable_maps_to_stop(self, classifier) -> None:
        """验收(sandbox unavailable→stop): DockerUnavailableError →
        SANDBOX_UNAVAILABLE，STOP——Fail Closed，绝不降级裸机（I3）。"""
        f = _classify(classifier, DockerUnavailableError("docker down"), FailureStage.SANDBOX)
        assert f.code == AgentErrorCode.SANDBOX_UNAVAILABLE
        assert f.category == ErrorCategory.SECURITY
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.STOP

    def test_keyboard_interrupt_maps_to_pause(self, classifier) -> None:
        """验收(Ctrl+C→PAUSED): KeyboardInterrupt → USER_INTERRUPT，
        PAUSE——中断是 Runtime Control Flow 不是 Failure（I6）。"""
        f = _classify(classifier, KeyboardInterrupt(), FailureStage.MODEL_CALL)
        assert f.code == AgentErrorCode.USER_INTERRUPT
        assert f.category == ErrorCategory.USER_INTERRUPT
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.PAUSE


class TestStageSensitivity:
    """day3 §三十七：同一个异常在不同 stage 映射不同 code。"""

    def test_timeout_in_model_call_is_model_timeout(self, classifier) -> None:
        """验收(stage 敏感性-模型): TimeoutError + MODEL_CALL →
        MODEL_TIMEOUT → RETRY。"""
        f = _classify(classifier, TimeoutError("x"), FailureStage.MODEL_CALL)
        assert f.code == AgentErrorCode.MODEL_TIMEOUT

    def test_timeout_in_verification_is_test_timeout_not_model(
        self, classifier
    ) -> None:
        """验收(stage 敏感性-验证): VerificationStatus.TIMED_OUT 在
        VERIFICATION → TEST_TIMEOUT → REPAIR（不是 MODEL_TIMEOUT 的
        RETRY——重跑测试不能修死循环，T13）。"""
        f = _classify(
            classifier, VerificationStatus.TIMED_OUT, FailureStage.VERIFICATION
        )
        assert f.code == AgentErrorCode.TEST_TIMEOUT
        assert f.recommended_recovery == RecoveryAction.REPAIR
        assert f.code != AgentErrorCode.MODEL_TIMEOUT

    def test_timeout_without_stage_semantics_falls_to_unknown(
        self, classifier
    ) -> None:
        """验收(stage 敏感性-兜底): TimeoutError 在没有超时语义的
        stage（GIT）→ UNKNOWN（fail closed）——不盲目按类型 Retry。
        （COMMAND_EXECUTION/VERIFICATION 已有各自的 Timeout 语义：
        分别 → TOOL_TIMEOUT / TEST_TIMEOUT，见 50 Case corpus。）"""
        f = _classify(classifier, TimeoutError("x"), FailureStage.GIT)
        assert f.code == AgentErrorCode.UNKNOWN
        assert f.retryable is False


class TestStageAndMetadataInputs:
    """stage/operation/metadata 输入必须确实影响结果（§十一）。"""

    def test_operation_written_into_metadata(self, classifier) -> None:
        """验收(operation 输入): operation 进入 metadata['operation']——
        证明该输入被消费而非忽略。"""
        f = _classify(
            classifier, _FakeStatusError("x", 503),
            FailureStage.MODEL_CALL, operation="plan_generation",
        )
        assert f.metadata["operation"] == "plan_generation"

    def test_caller_metadata_preserved(self, classifier) -> None:
        """验收(metadata 合并): 调用方传入的 metadata 保留在结果中。"""
        f = _classify(
            classifier, _FakeStatusError("x", 503),
            FailureStage.MODEL_CALL, metadata={"request_id": "req-9"},
        )
        assert f.metadata["request_id"] == "req-9"

    def test_failure_id_reflects_stage_and_code(self, classifier) -> None:
        """验收(确定性 failure_id): task:stage:code:attempt——
        stage 输入直接体现在 failure_id 中。"""
        f = _classify(
            classifier, _FakeStatusError("x", 503),
            FailureStage.MODEL_CALL, task_id="t1", attempt=2,
        )
        assert f.failure_id == "t1:model_call:model_overloaded:2"


class TestCausePreservationAndSanitization:
    """T17（cause preservation）与 T18（secret-safe）。"""

    def test_source_type_and_message_preserved(self, classifier) -> None:
        """验收(T17): 原始异常类型名与消息保留在 source_type /
        source_message——wrap not erase。"""
        error = _FakeStatusError("invalid api key sk-abc", 401)
        f = _classify(classifier, error, FailureStage.MODEL_CALL)
        assert f.source_type == "_FakeStatusError"
        assert f.source_message == "invalid api key sk-abc"
        assert f.cause is error

    def test_public_message_never_contains_raw_error_text(
        self, classifier
    ) -> None:
        """验收(T18): message 是固定模板，绝不含原始异常文本——
        密钥/路径不会通过用户消息泄漏。"""
        error = _FakeStatusError("invalid api key sk-abc123secret", 401)
        f = _classify(classifier, error, FailureStage.MODEL_CALL)
        assert "sk-abc123secret" not in f.message
        assert "sk-" not in f.message
        # 原始文本仍在内部诊断字段
        assert "sk-abc123secret" in (f.source_message or "")

    def test_context_overflow_belongs_to_context_category(
        self, classifier
    ) -> None:
        """验收(domain category ≠ exception origin, §七十一):
        Provider 报上下文超限 → CONTEXT_BUDGET_EXCEEDED（CONTEXT 类）
        + COMPACT_CONTEXT，即使底层异常来自模型 API。"""
        error = _FakeStatusError("maximum context length exceeded", 400)
        f = _classify(classifier, error, FailureStage.MODEL_CALL)
        assert f.category == ErrorCategory.CONTEXT
        assert f.code == AgentErrorCode.CONTEXT_BUDGET_EXCEEDED
        assert f.recommended_recovery == RecoveryAction.COMPACT_CONTEXT


class TestRecommendedT09T10:
    """T09（invalid auth→stop）与 T10（quota→stop）。"""

    def test_invalid_api_key_maps_to_stop(self, classifier) -> None:
        """验收(T09): 401 → MODEL_AUTH_FAILED，retryable=False，STOP——
        API Key 错误重试永远不会自己变好。"""
        f = _classify(classifier, _FakeStatusError("bad key", 401), FailureStage.MODEL_CALL)
        assert f.code == AgentErrorCode.MODEL_AUTH_FAILED
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.STOP

    def test_quota_exceeded_maps_to_stop(self, classifier) -> None:
        """验收(T10): 402 → MODEL_QUOTA_EXCEEDED，STOP——
        billing/quota 类错误重复 Retry 不能恢复服务。"""
        f = _classify(classifier, _FakeStatusError("quota", 402), FailureStage.MODEL_CALL)
        assert f.code == AgentErrorCode.MODEL_QUOTA_EXCEEDED
        assert f.retryable is False
        assert f.recommended_recovery == RecoveryAction.STOP
