"""codeteam.llm.error_mapper — Provider 异常归一化层（W4D5 Step 4）。

定位（day5 §三十一，Day 3 Taxonomy 与 Day 5 Provider Runtime 的连接点）：

    Provider A Exception  ─┐
    Provider B Exception  ─┼→ ProviderErrorMapper → NormalizedModelError
    传输层 TimeoutError    ─┘         │
                                      ▼
                        ErrorClassifier（读字段，不再猜消息文本）
                                      │
                          RecoveryPolicy / RetryPolicy（Day 3，零改动）

设计纪律：
- 不动 openai_compatible.py 的传输层重试（DD-W4-D3-01 三层分工）
- mapper 不认识 → 返回 None，交下一 mapper / 现有消息级兜底
- cause preservation：raise ... from error，traceback 不丢根因
"""
from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar


class NormalizedModelErrorCode(str, Enum):
    """7 类统一语义码（与 AgentErrorCode.MODEL_* 同构，§三十一）。"""

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    AUTH = "auth"
    CONTEXT_OVERFLOW = "context_overflow"
    INVALID_REQUEST = "invalid_request"
    SERVER = "server"
    UNKNOWN = "unknown"


# 与 AgentErrorCode 的直查映射（classifier 消费；两 Enum 一一对应）
TO_AGENT_ERROR_CODE: dict[
    NormalizedModelErrorCode, str
] = {
    NormalizedModelErrorCode.RATE_LIMIT: "model_rate_limit",
    NormalizedModelErrorCode.TIMEOUT: "model_timeout",
    NormalizedModelErrorCode.AUTH: "model_auth_failed",
    NormalizedModelErrorCode.CONTEXT_OVERFLOW: "context_budget_exceeded",
    NormalizedModelErrorCode.INVALID_REQUEST: "model_invalid_request",
    NormalizedModelErrorCode.SERVER: "model_overloaded",
    NormalizedModelErrorCode.UNKNOWN: "unknown",
}


class NormalizedModelError(Exception):
    """归一化的 Provider 错误（异常即数据载体）。

    classifier 读 self.normalized_code 直查分类——分类依据从
    "消息关键词猜" 升级为 "抛出点的结构化事实"。
    """

    def __init__(
        self,
        *,
        message: str,
        provider_id: str,
        normalized_code: NormalizedModelErrorCode,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.normalized_code = normalized_code
        self.metadata = dict(metadata or {})
        super().__init__(
            f"[{provider_id}/{normalized_code.value}] {message}"
        )


class ProviderErrorMapper:
    """基类：子类实现 map()，不认识返回 None。"""

    provider_id: str = ""

    def map(
        self,
        error: Exception,
    ) -> NormalizedModelError | None:
        raise NotImplementedError


_STATUS_CODE_MAP: dict[int, NormalizedModelErrorCode] = {
    429: NormalizedModelErrorCode.RATE_LIMIT,
    401: NormalizedModelErrorCode.AUTH,
    403: NormalizedModelErrorCode.AUTH,
    400: NormalizedModelErrorCode.INVALID_REQUEST,
    408: NormalizedModelErrorCode.TIMEOUT,
    500: NormalizedModelErrorCode.SERVER,
    502: NormalizedModelErrorCode.SERVER,
    503: NormalizedModelErrorCode.SERVER,
    504: NormalizedModelErrorCode.TIMEOUT,
}

_OVERFLOW_MARKERS = (
    "context_length_exceeded",
    "context window",
    "maximum context",
    "prompt is too long",
    "too many tokens",
)


class OpenAICompatibleErrorMapper(ProviderErrorMapper):
    """OpenAI 兼容方言：status_code + 消息特征。"""

    provider_id = "openai-compatible"

    def map(self, error: Exception) -> NormalizedModelError | None:
        status = self._status_of(error)
        if status is not None and status in _STATUS_CODE_MAP:
            code = _STATUS_CODE_MAP[status]
            # 400 也可能是 overflow（各家把 overflow 塞 400 的情况常见）
            if (
                code is NormalizedModelErrorCode.INVALID_REQUEST
                and self._looks_like_overflow(error)
            ):
                code = NormalizedModelErrorCode.CONTEXT_OVERFLOW
            return NormalizedModelError(
                message=str(error),
                provider_id=self.provider_id,
                normalized_code=code,
                metadata=self._extract_meta(error, status),
            )

        if self._looks_like_overflow(error):
            return NormalizedModelError(
                message=str(error),
                provider_id=self.provider_id,
                normalized_code=NormalizedModelErrorCode.CONTEXT_OVERFLOW,
                metadata=self._extract_meta(error, status),
            )
        if isinstance(error, TimeoutError):
            return NormalizedModelError(
                message=str(error),
                provider_id=self.provider_id,
                normalized_code=NormalizedModelErrorCode.TIMEOUT,
                metadata=self._extract_meta(error, None),
            )
        return None  # 不认识 → 下一个 mapper / 消息级兜底

    # ── 字段探测（各家异常字段不齐，getattr 三参防御）──

    @staticmethod
    def _status_of(error: Exception) -> int | None:
        for attr in ("status_code", "status", "code"):
            value = getattr(error, attr, None)
            if isinstance(value, int):
                return value
        return None

    @staticmethod
    def _looks_like_overflow(error: Exception) -> bool:
        text = str(error).lower()
        return any(marker in text for marker in _OVERFLOW_MARKERS)

    @staticmethod
    def _extract_meta(error: Exception, status: int | None) -> dict:
        meta: dict[str, Any] = {}
        if status is not None:
            meta["status_code"] = status
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            meta["retry_after"] = retry_after
        request_id = getattr(error, "request_id", None)
        if request_id is not None:
            meta["request_id"] = str(request_id)
        return meta


class AnthropicStyleErrorMapper(ProviderErrorMapper):
    """第二方言：anthropic 风格异常（类型名 + type 字段）。

    演示"新增 Provider = 新增一个 mapper 类，零 core 改动"——
    DD-W4-D5-02 / Ablation A4 的度量素材。
    """

    provider_id = "anthropic-style"

    _TYPE_MAP: ClassVar[dict[str, NormalizedModelErrorCode]] = {
        "rate_limit_error": NormalizedModelErrorCode.RATE_LIMIT,
        "authentication_error": NormalizedModelErrorCode.AUTH,
        "permission_error": NormalizedModelErrorCode.AUTH,
        "invalid_request_error": NormalizedModelErrorCode.INVALID_REQUEST,
        "overloaded_error": NormalizedModelErrorCode.SERVER,
        "api_error": NormalizedModelErrorCode.SERVER,
    }

    def map(self, error: Exception) -> NormalizedModelError | None:
        error_type = getattr(error, "type", None) or getattr(
            error, "error_type", None
        )
        if isinstance(error_type, str) and error_type in self._TYPE_MAP:
            return NormalizedModelError(
                message=str(error),
                provider_id=self.provider_id,
                normalized_code=self._TYPE_MAP[error_type],
                metadata=self._meta(error),
            )
        if isinstance(error, TimeoutError):
            return NormalizedModelError(
                message=str(error),
                provider_id=self.provider_id,
                normalized_code=NormalizedModelErrorCode.TIMEOUT,
                metadata=self._meta(error),
            )
        return None

    @staticmethod
    def _meta(error: Exception) -> dict:
        meta: dict[str, Any] = {}
        for attr in ("retry_after", "request_id"):
            value = getattr(error, attr, None)
            if value is not None:
                meta[attr] = value
        return meta


class MapperChain:
    """按注册顺序尝试多个 mapper；全不认识 → None。"""

    def __init__(self, mappers: tuple[ProviderErrorMapper, ...]) -> None:
        self._mappers = mappers

    def map(self, error: Exception) -> NormalizedModelError | None:
        for mapper in self._mappers:
            mapped = mapper.map(error)
            if mapped is not None:
                return mapped
        return None


def normalize_provider_error(
    error: Exception,
    *,
    mappers: MapperChain,
) -> NormalizedModelError | None:
    """入口：归一化失败返回 None（调用方决定兜底策略）。"""
    return mappers.map(error)