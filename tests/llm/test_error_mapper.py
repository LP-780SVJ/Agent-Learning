"""W4D5 Step 4：ModelErrorMapper 归一化 + classifier 接入测试。

覆盖 day5 §四十六 Model 矩阵末三行（双 Provider 同语义 / resume 除外）：
- Provider A 的 429 与 Provider B 的 rate_limit_error → 同一 AgentFailure.code
- CONTEXT_OVERFLOW → CONTEXT_BUDGET_EXCEEDED（与 ⑧ 消息路径同语义收敛）
- classifier 归一化路径零消息猜测、metadata 透传、cause 保留
"""
from __future__ import annotations

import pytest

from codeteam.failures.classifier import ErrorClassifier
from codeteam.failures.models import AgentErrorCode, FailureStage, RecoveryAction
from codeteam.llm.error_mapper import (
    AnthropicStyleErrorMapper,
    MapperChain,
    NormalizedModelError,
    NormalizedModelErrorCode,
    OpenAICompatibleErrorMapper,
)


class _FakeHTTPError(Exception):
    """OpenAI 兼容方言的假异常（字段不齐的真实世界模拟）。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class _FakeAnthropicError(Exception):
    """Anthropic 方言假异常：type 字段 + 可选 retry_after。"""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.type = error_type
        self.retry_after = retry_after


def _chain() -> MapperChain:
    return MapperChain(
        (
            OpenAICompatibleErrorMapper(),
            AnthropicStyleErrorMapper(),
        )
    )


class TestOpenAICompatibleMapper:
    def test_429_maps_rate_limit_with_retry_after(self) -> None:
        error = _FakeHTTPError(
            "Too many requests", status_code=429, retry_after=1.5
        )
        mapped = _chain().map(error)
        assert mapped is not None
        assert mapped.normalized_code is NormalizedModelErrorCode.RATE_LIMIT
        assert mapped.metadata["retry_after"] == 1.5
        assert mapped.metadata["status_code"] == 429
        assert mapped.provider_id == "openai-compatible"

    def test_401_maps_auth(self) -> None:
        mapped = _chain().map(_FakeHTTPError("bad key", status_code=401))
        assert mapped is not None
        assert mapped.normalized_code is NormalizedModelErrorCode.AUTH

    def test_503_maps_server(self) -> None:
        mapped = _chain().map(_FakeHTTPError("overloaded", status_code=503))
        assert mapped is not None
        assert mapped.normalized_code is NormalizedModelErrorCode.SERVER

    def test_400_with_overflow_marker_maps_context_overflow(self) -> None:
        """400 + overflow 特征 → CONTEXT_OVERFLOW（不是 INVALID_REQUEST）。"""
        error = _FakeHTTPError(
            "This model's maximum context length is 128000 tokens",
            status_code=400,
        )
        mapped = _chain().map(error)
        assert mapped is not None
        assert mapped.normalized_code is NormalizedModelErrorCode.CONTEXT_OVERFLOW

    def test_400_without_marker_maps_invalid_request(self) -> None:
        mapped = _chain().map(_FakeHTTPError("bad param", status_code=400))
        assert mapped is not None
        assert (
            mapped.normalized_code
            is NormalizedModelErrorCode.INVALID_REQUEST
        )

    def test_timeout_exception_maps_timeout(self) -> None:
        mapped = _chain().map(TimeoutError("request timed out"))
        assert mapped is not None
        assert mapped.normalized_code is NormalizedModelErrorCode.TIMEOUT

    def test_unrecognized_returns_none(self) -> None:
        """不认识 → None（链式兜底协议），绝不硬猜。"""
        assert _chain().map(ValueError("啥也不是")) is None


class TestAnthropicStyleMapper:
    def test_rate_limit_error_type_maps(self) -> None:
        error = _FakeAnthropicError(
            "rate limited", error_type="rate_limit_error", retry_after=2.0
        )
        mapped = AnthropicStyleErrorMapper().map(error)
        assert mapped is not None
        assert mapped.normalized_code is NormalizedModelErrorCode.RATE_LIMIT
        assert mapped.provider_id == "anthropic-style"
        assert mapped.metadata["retry_after"] == 2.0

    def test_type_not_in_map_returns_none(self) -> None:
        error = _FakeAnthropicError("???", error_type="novel_error")
        assert AnthropicStyleErrorMapper().map(error) is None

    def test_openai_mapper_leaves_anthropic_alone(self) -> None:
        """方言隔离：openai mapper 不认识 anthropic 异常。"""
        error = _FakeAnthropicError(
            "rate limited", error_type="rate_limit_error"
        )
        assert OpenAICompatibleErrorMapper().map(error) is None


class TestMapperChain:
    def test_first_match_wins(self) -> None:
        """链序优先：openai 在前，anthropic 兜后。"""
        error = _FakeAnthropicError(
            "rate limited", error_type="rate_limit_error"
        )
        mapped = _chain().map(error)
        assert mapped is not None
        assert mapped.provider_id == "anthropic-style"  # 被 anthropic 接住

    def test_all_mappers_miss_returns_none(self) -> None:
        assert _chain().map(RuntimeError("mystery")) is None


class TestClassifierNormalizedPath:
    """①b 分支：读字段直查，零消息猜测。"""

    def _classify(self, error: Exception):
        return ErrorClassifier().classify(
            error=error,
            stage=FailureStage.MODEL_CALL,
            operation="plan_generation",
            task_id="task-1",
            attempt=1,
        )

    def test_normalized_rate_limit_reads_field(self) -> None:
        error = NormalizedModelError(
            message="Too many requests",
            provider_id="openai-compatible",
            normalized_code=NormalizedModelErrorCode.RATE_LIMIT,
            metadata={"retry_after": 1.5, "status_code": 429},
        )
        failure = self._classify(error)
        assert failure.code is AgentErrorCode.MODEL_RATE_LIMIT
        assert failure.retryable is True
        assert failure.recommended_recovery is RecoveryAction.RETRY
        # metadata 透传：provider 归因 + RetryPolicy 的 retry_after
        assert failure.metadata["provider_id"] == "openai-compatible"
        assert failure.metadata["retry_after"] == 1.5

    def test_overflow_maps_to_context_budget_exceeded(self) -> None:
        """★ 锁定 CONTEXT_OVERFLOW → CONTEXT_BUDGET_EXCEEDED。

        与 ⑧ 消息路径同语义（CONTEXT 类 / COMPACT_CONTEXT）——
        归一化路径不得产生分类分歧。曾错映射 model_context_overflow
        （_SIGNALS 无此键 → KeyError），此测试防回归。
        """
        error = NormalizedModelError(
            message="maximum context length exceeded",
            provider_id="openai-compatible",
            normalized_code=NormalizedModelErrorCode.CONTEXT_OVERFLOW,
        )
        failure = self._classify(error)
        assert failure.code is AgentErrorCode.CONTEXT_BUDGET_EXCEEDED
        assert failure.category.value == "context"
        assert (
            failure.recommended_recovery
            is RecoveryAction.COMPACT_CONTEXT
        )

    def test_two_providers_same_code(self) -> None:
        """★ §四十六末行：A 的 429 与 B 的 rate_limit_error → 同 code。"""
        a = NormalizedModelError(
            message="429",
            provider_id="openai-compatible",
            normalized_code=NormalizedModelErrorCode.RATE_LIMIT,
        )
        b = NormalizedModelError(
            message="rate limited",
            provider_id="anthropic-style",
            normalized_code=NormalizedModelErrorCode.RATE_LIMIT,
        )
        failure_a = self._classify(a)
        failure_b = self._classify(b)
        assert failure_a.code is failure_b.code
        assert failure_a.metadata["provider_id"] == "openai-compatible"
        assert failure_b.metadata["provider_id"] == "anthropic-style"

    def test_stage_independent(self) -> None:
        """①b 不 gate stage：归一化事实比 stage 标签可信。"""
        error = NormalizedModelError(
            message="x",
            provider_id="p",
            normalized_code=NormalizedModelErrorCode.TIMEOUT,
        )
        failure = ErrorClassifier().classify(
            error=error,
            stage=FailureStage.CONTEXT_RETRIEVAL,  # 非 MODEL_CALL
            operation="op",
            task_id="t",
        )
        assert failure.code is AgentErrorCode.MODEL_TIMEOUT

    def test_cause_preserved(self) -> None:
        """cause preservation：归一化异常自身作为 cause 进 AgentFailure。"""
        raw = _FakeHTTPError("Too many requests", status_code=429)
        mapped = _chain().map(raw)
        assert mapped is not None
        failure = self._classify(mapped)
        assert failure.cause is mapped
        assert failure.source_type == "NormalizedModelError"

    def test_message_template_not_raw_text(self) -> None:
        """用户可见消息走 _MESSAGES 固定模板（T18），不含原始异常文本。"""
        error = NormalizedModelError(
            message="sk-secret-123 leaked in message",
            provider_id="p",
            normalized_code=NormalizedModelErrorCode.RATE_LIMIT,
        )
        failure = self._classify(error)
        assert "sk-secret" not in failure.message


class TestLegacyPathRegression:
    """①b 不影响既有路径：传输层裸异常仍走 ⑧ _classify_model_call。"""

    def test_raw_429_still_classified_by_model_call(self) -> None:
        failure = ErrorClassifier().classify(
            error=_FakeHTTPError("429", status_code=429, retry_after=3.0),
            stage=FailureStage.MODEL_CALL,
            operation="op",
            task_id="t",
        )
        assert failure.code is AgentErrorCode.MODEL_RATE_LIMIT
        assert failure.metadata["retry_after"] == 3.0

    @pytest.mark.parametrize(
        "raw,mapped_code",
        [
            (_FakeHTTPError("x", status_code=429), NormalizedModelErrorCode.RATE_LIMIT),
            (_FakeHTTPError("x", status_code=401), NormalizedModelErrorCode.AUTH),
            (_FakeHTTPError("x", status_code=503), NormalizedModelErrorCode.SERVER),
        ],
    )
    def test_raw_and_normalized_paths_agree(
        self,
        raw: Exception,
        mapped_code: NormalizedModelErrorCode,
    ) -> None:
        """路径收敛：裸异常（⑧）与归一化（①b）对同一错误给同 code。"""
        raw_failure = ErrorClassifier().classify(
            error=raw,
            stage=FailureStage.MODEL_CALL,
            operation="op",
            task_id="t",
        )
        mapped = _chain().map(raw)
        assert mapped is not None
        assert mapped.normalized_code is mapped_code
        normalized_failure = ErrorClassifier().classify(
            error=mapped,
            stage=FailureStage.MODEL_CALL,
            operation="op",
            task_id="t",
        )
        assert raw_failure.code is normalized_failure.code
