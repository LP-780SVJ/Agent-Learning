"""
RetryPolicy: 决定能否重试、应该等多久。

与 RecoveryPolicy 的分工：
- RecoveryPolicy：失败 → 动作类型（该不该 RETRY）
- RetryPolicy：    RETRY 的语义细节（能不能重试 + 等多久）

只算 delay，不 time.sleep——等待由 Orchestrator 或注入的 sleeper 完成。
jitter 通过注入 random.Random 实现确定性测试。
"""
from __future__ import annotations

import random

from pydantic import BaseModel

from codeteam.failures.models import AgentFailure


class RetryDecision(BaseModel):
    """一次重试决策。

    Attributes:
        should_retry: 是否应该重试
        delay_seconds: 建议等待秒数（should_retry=False 时为 None）
        attempt: 下一次尝试的编号（1-based；不再重试时等于当前 attempt）
        reason: 决策原因（"ok" / "not_retryable" /
                "max_attempts_exhausted" / "max_total_delay_exhausted"）
    """
    should_retry: bool
    delay_seconds: float | None
    attempt: int
    reason: str


class RetryPolicy:
    """指数退避 + jitter + Retry-After + 双预算的重试策略。

    用法：
        policy = RetryPolicy(rng=random.Random(42))  # 测试注入固定 seed
        decision = policy.decide(failure, elapsed_retry_seconds=2.5)
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        jitter: bool = True,
        max_total_delay_seconds: float = 60.0,
        rng: random.Random | None = None,
    ) -> None:
        """初始化 RetryPolicy。

        Args:
            max_attempts: 同一操作的最大尝试次数（含首次）
            base_delay_seconds: 退避基数（第一次重试的等待时间）
            max_delay_seconds: 单次等待上限（指数增长封顶）
            jitter: 是否加随机抖动（防 Thundering Herd）
            max_total_delay_seconds: 累计等待总上限（时间预算）
            rng: 随机数生成器。测试传入 random.Random(seed) 获得确定性。
        """
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.jitter = jitter
        self.max_total_delay_seconds = max_total_delay_seconds
        self._rng = rng if rng is not None else random.Random()

    # ── 主入口 ───────────────────────────────────────────────

    def decide(
        self,
        failure: AgentFailure,
        *,
        elapsed_retry_seconds: float = 0.0,
    ) -> RetryDecision:
        """对一次失败给出重试决策。

        判定顺序（前三条任一不满足立即拒绝）：
        ① failure.retryable == False → 不重试
        ② attempt >= max_attempts → 次数预算耗尽
        ③ elapsed >= max_total_delay → 时间预算耗尽
        ④ 否则计算 delay：backoff → Retry-After 取大 → jitter
        """
        # ① 不可重试（纵深防御：RecoveryPolicy 已拦截，这里再保一次）
        if not failure.retryable:
            return RetryDecision(
                should_retry=False,
                delay_seconds=None,
                attempt=failure.attempt,
                reason="not_retryable",
            )

        # ② 次数预算耗尽（I7 / T15）
        if failure.attempt >= self.max_attempts:
            return RetryDecision(
                should_retry=False,
                delay_seconds=None,
                attempt=failure.attempt,
                reason="max_attempts_exhausted",
            )

        # ③ 时间预算耗尽（day3 §二十六：attempt count 控制不了总等待时间）
        if elapsed_retry_seconds >= self.max_total_delay_seconds:
            return RetryDecision(
                should_retry=False,
                delay_seconds=None,
                attempt=failure.attempt,
                reason="max_total_delay_exhausted",
            )

        # ④ 计算 delay
        delay = self._compute_delay(failure)

        return RetryDecision(
            should_retry=True,
            delay_seconds=round(delay, 3),
            attempt=failure.attempt + 1,
            reason="ok",
        )

    # ── delay 计算 ───────────────────────────────────────────

    def _compute_delay(self, failure: AgentFailure) -> float:
        """指数退避 + Retry-After 取大 + jitter。

        公式：
            backoff = min(max_delay, base × 2^(attempt-1))
            retry_after 存在 → delay = max(backoff, retry_after)
            jitter 开启 → delay = delay × uniform(0.8, 1.2)
        """
        # 指数退避：attempt=1（首次失败）→ base×1；attempt=2 → base×2 ...
        exponent = failure.attempt - 1
        backoff = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** exponent),
        )

        # Retry-After（classifier 在 429 时写入 metadata）
        retry_after = failure.metadata.get("retry_after")
        if retry_after is not None:
            delay = max(backoff, float(retry_after))
        else:
            delay = backoff

        # Jitter：±20% 随机抖动，打破同步重试（Thundering Herd）
        if self.jitter:
            delay = delay * self._rng.uniform(0.8, 1.2)

        return delay