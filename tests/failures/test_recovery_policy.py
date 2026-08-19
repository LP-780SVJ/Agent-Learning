"""tests/failures/test_recovery_policy.py — RecoveryPolicy 单元测试。

对应 day3.md §九十 分层原则的 Policy 单测层：
只断言「AgentFailure → RecoveryAction」，
不涉及 Orchestrator 的执行行为。

覆盖：
- SECURITY 类硬编码 STOP（I1/I2/I3 的 Policy 层防线，§四十~四十一）
- T14：安全失败不随 attempt 改变
- USER_INTERRUPT → PAUSE（I6）
- 一致性守卫（retryable=False 却建议 RETRY → STOP）
- 正常透传（方案 B，§四十九）
"""

from __future__ import annotations

import pytest

from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.failures.recovery import RecoveryPolicy


def _make(
    *,
    code: AgentErrorCode,
    category: ErrorCategory,
    recommended: RecoveryAction,
    retryable: bool,
    attempt: int = 1,
) -> AgentFailure:
    return AgentFailure(
        failure_id=f"f-{code.value}",
        task_id="t1",
        category=category,
        code=code,
        stage=FailureStage.MODEL_CALL,
        message="test",
        transient=False,
        retryable=retryable,
        attempt=attempt,
        recommended_recovery=recommended,
    )


@pytest.fixture
def policy() -> RecoveryPolicy:
    return RecoveryPolicy()


class TestSecurityHardcodedStop:
    """I1/I2/I3：SECURITY 类硬编码 STOP（§四十~四十一）。"""

    @pytest.mark.parametrize(
        "code",
        [
            AgentErrorCode.POLICY_DENIED,
            AgentErrorCode.APPROVAL_DENIED,
            AgentErrorCode.SANDBOX_UNAVAILABLE,
            AgentErrorCode.SANDBOX_VIOLATION,
        ],
    )
    def test_security_stops_even_if_recommended_is_retry(
        self, policy, code
    ) -> None:
        """验收(I1/I2/I3 纵深防御): 即使 classifier 表被误改成
        recommended=RETRY，Policy 仍按 category 拦截为 STOP——
        安全规则面向类别不面向个案。"""
        f = _make(
            code=code,
            category=ErrorCategory.SECURITY,
            recommended=RecoveryAction.RETRY,
            retryable=True,  # 故意配错：retryable=True 也不能放行
        )
        assert policy.decide(f) == RecoveryAction.STOP

    def test_security_stop_does_not_change_with_attempt(
        self, policy
    ) -> None:
        """验收(T14): 安全失败在 attempt=5 仍 STOP——
        不随尝试次数改变，不能让 Agent 通过反复尝试磨损安全边界。"""
        f = _make(
            code=AgentErrorCode.POLICY_DENIED,
            category=ErrorCategory.SECURITY,
            recommended=RecoveryAction.RETRY,
            retryable=True,
            attempt=5,
        )
        assert policy.decide(f) == RecoveryAction.STOP


class TestUserInterrupt:
    """I6：USER_INTERRUPT → PAUSE（§四十五）。"""

    def test_user_interrupt_pauses_even_if_recommended_stop(
        self, policy
    ) -> None:
        """验收(I6): 即使 recommended 被误配成 STOP，
        USER_INTERRUPT 仍 PAUSE——中断不是失败。"""
        f = _make(
            code=AgentErrorCode.USER_INTERRUPT,
            category=ErrorCategory.USER_INTERRUPT,
            recommended=RecoveryAction.STOP,
            retryable=False,
        )
        assert policy.decide(f) == RecoveryAction.PAUSE


class TestConsistencyGuard:
    """一致性守卫：自相矛盾的失败不重试。"""

    def test_not_retryable_with_retry_recommendation_stops(
        self, policy
    ) -> None:
        """验收(守卫): retryable=False 但建议 RETRY → STOP——
        防御 classifier 表误维护。"""
        f = _make(
            code=AgentErrorCode.MODEL_AUTH_FAILED,
            category=ErrorCategory.MODEL,
            recommended=RecoveryAction.RETRY,
            retryable=False,
        )
        assert policy.decide(f) == RecoveryAction.STOP


class TestPassthrough:
    """方案 B：其余透传 classifier 建议（§四十九）。"""

    @pytest.mark.parametrize(
        "code,category,recommended",
        [
            (AgentErrorCode.MODEL_RATE_LIMIT, ErrorCategory.MODEL, RecoveryAction.RETRY),
            (AgentErrorCode.TEST_FAILED, ErrorCategory.TEST, RecoveryAction.REPAIR),
            (AgentErrorCode.PATCH_CONTEXT_MISMATCH, ErrorCategory.PATCH, RecoveryAction.REREAD_AND_REGENERATE),
            (AgentErrorCode.CONTEXT_INSUFFICIENT, ErrorCategory.CONTEXT, RecoveryAction.RETRIEVE_MORE_CONTEXT),
            (AgentErrorCode.CONTEXT_BUDGET_EXCEEDED, ErrorCategory.CONTEXT, RecoveryAction.COMPACT_CONTEXT),
        ],
    )
    def test_normal_failures_pass_through_recommendation(
        self, policy, code, category, recommended
    ) -> None:
        """验收(透传): 非安全、非中断、无矛盾 → 透传建议动作。"""
        f = _make(
            code=code,
            category=category,
            recommended=recommended,
            retryable=(recommended == RecoveryAction.RETRY),
        )
        assert policy.decide(f) == recommended


class TestPolicyIsPureDecision:
    """Policy 只决策不执行（§四十七/六十二）。"""

    def test_decide_has_no_side_effects(self, policy) -> None:
        """验收(纯决策): decide 不修改 failure、不调用外部组件——
        连续调用结果一致。"""
        f = _make(
            code=AgentErrorCode.MODEL_RATE_LIMIT,
            category=ErrorCategory.MODEL,
            recommended=RecoveryAction.RETRY,
            retryable=True,
        )
        first = policy.decide(f)
        second = policy.decide(f)
        assert first == second == RecoveryAction.RETRY
