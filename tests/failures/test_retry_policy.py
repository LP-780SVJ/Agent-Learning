"""tests/failures/test_retry_policy.py — RetryPolicy 单元测试。

对应 day3.md §九十 分层原则的 Policy 单测层：
只断言「failure + elapsed → RetryDecision」，不真实 sleep。

覆盖：
- 指数退避公式（jitter=False 精确断言，§二十三）
- max_delay 封顶
- Retry-After 取大（T16，§二十五）
- 双预算耗尽（T15 + I7 语义，§二十六）
- jitter 确定性与边界（注入 random.Random，§六十五）
- 纯计算无 sleep
"""

from __future__ import annotations

import random
import time

from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.failures.retry import RetryPolicy


def _make(
    *,
    attempt: int = 1,
    retryable: bool = True,
    metadata: dict | None = None,
) -> AgentFailure:
    return AgentFailure(
        failure_id=f"f{attempt}",
        task_id="t1",
        category=ErrorCategory.MODEL,
        code=AgentErrorCode.MODEL_RATE_LIMIT,
        stage=FailureStage.MODEL_CALL,
        message="test",
        transient=True,
        retryable=retryable,
        attempt=attempt,
        recommended_recovery=RecoveryAction.RETRY,
        metadata=metadata or {},
    )


class TestExponentialBackoff:
    """§二十三：delay = min(max_delay, base × 2^(attempt-1))。"""

    def test_backoff_doubles_each_attempt(self) -> None:
        """验收(退避公式): jitter=False 时 delay 精确等于
        base × 2^(attempt-1)——attempt=1 等 1s、attempt=2 等 2s ..."""
        policy = RetryPolicy(max_attempts=5, jitter=False)
        expected = {1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0}
        for attempt, want in expected.items():
            d = policy.decide(_make(attempt=attempt))
            assert d.should_retry is True
            assert d.delay_seconds == want, f"attempt={attempt}"

    def test_max_delay_caps_backoff(self) -> None:
        """验收(封顶): max_delay_seconds 封顶指数增长——
        attempt=4 的 8s 被封到 3s。"""
        policy = RetryPolicy(max_attempts=5, max_delay_seconds=3.0, jitter=False)
        d = policy.decide(_make(attempt=4))
        assert d.delay_seconds == 3.0


class TestRetryAfter:
    """T16：Retry-After 生效（§二十五）。"""

    def test_retry_after_larger_than_backoff_wins(self) -> None:
        """验收(T16): 服务端 Retry-After 5.0 > 本地退避 2.0 →
        等 5.0——比服务端要求早重试只会再吃 429。"""
        policy = RetryPolicy(max_attempts=3, jitter=False)
        d = policy.decide(_make(attempt=2, metadata={"retry_after": 5.0}))
        assert d.delay_seconds == 5.0

    def test_backoff_larger_than_retry_after_wins(self) -> None:
        """验收(T16 反向): 本地退避 4.0 > Retry-After 1.0 →
        等 4.0——宁多勿少。"""
        policy = RetryPolicy(max_attempts=5, jitter=False)
        d = policy.decide(_make(attempt=3, metadata={"retry_after": 1.0}))
        assert d.delay_seconds == 4.0


class TestBudgetExhaustion:
    """T15 + I7 语义：次数与时间双预算（§二十六）。"""

    def test_max_attempts_exhausted(self) -> None:
        """验收(T15): attempt=3 且 max_attempts=3 → 不重试，
        reason=max_attempts_exhausted——permanent 失败不无限 Retry。"""
        policy = RetryPolicy(max_attempts=3, jitter=False)
        d = policy.decide(_make(attempt=3))
        assert d.should_retry is False
        assert d.reason == "max_attempts_exhausted"
        assert d.delay_seconds is None

    def test_max_total_delay_exhausted(self) -> None:
        """验收(I7 时间预算): elapsed 61s > max_total 60s → 不重试，
        reason=max_total_delay_exhausted——attempt 数控制不了总等待时间。"""
        policy = RetryPolicy(jitter=False)
        d = policy.decide(_make(attempt=1), elapsed_retry_seconds=61.0)
        assert d.should_retry is False
        assert d.reason == "max_total_delay_exhausted"

    def test_not_retryable_rejected_first(self) -> None:
        """验收(纵深防御): retryable=False → 不重试，
        reason=not_retryable——即使 attempt 未到上限。"""
        policy = RetryPolicy(max_attempts=5, jitter=False)
        d = policy.decide(_make(attempt=1, retryable=False))
        assert d.should_retry is False
        assert d.reason == "not_retryable"


class TestJitterDeterminism:
    """§六十五：注入 random.Random 获得确定性；jitter 边界。"""

    def test_seeded_rng_produces_identical_decisions(self) -> None:
        """验收(jitter 确定性): 两个相同 seed 的 policy 产出完全
        相同的 delay——测试可复现。"""
        p1 = RetryPolicy(rng=random.Random(42))
        p2 = RetryPolicy(rng=random.Random(42))
        d1 = p1.decide(_make(attempt=1))
        d2 = p2.decide(_make(attempt=1))
        assert d1.delay_seconds == d2.delay_seconds

    def test_jitter_stays_within_twenty_percent(self) -> None:
        """验收(jitter 边界): 大量采样都落在 [0.8×, 1.2×] 基准区间。"""
        base = RetryPolicy(jitter=False).decide(_make(attempt=1)).delay_seconds
        assert base == 1.0
        sampled = [
            RetryPolicy(jitter=True, rng=random.Random(i))
            .decide(_make(attempt=1))
            .delay_seconds
            for i in range(50)
        ]
        assert all(0.8 <= v <= 1.2 for v in sampled)


class TestPureComputation:
    """Policy 只算 delay 不 sleep（§六十五）。"""

    def test_many_decisions_take_no_sleep_time(self) -> None:
        """验收(纯计算): 1000 次 decide 总耗时 < 1s——
        若内部有 time.sleep 此断言必然失败。"""
        policy = RetryPolicy(jitter=False)
        started = time.monotonic()
        for _ in range(1000):
            policy.decide(_make(attempt=1))
        elapsed = time.monotonic() - started
        assert elapsed < 1.0

    def test_decision_is_structured_and_exportable(self) -> None:
        """验收(周度数据出口): RetryDecision 可 JSON 序列化，
        含 should_retry/attempt/delay/reason 四个周度指标字段。"""
        policy = RetryPolicy(jitter=False)
        d = policy.decide(_make(attempt=1))
        data = d.model_dump()
        assert set(data.keys()) == {
            "should_retry", "delay_seconds", "attempt", "reason",
        }
