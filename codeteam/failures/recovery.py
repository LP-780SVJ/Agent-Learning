"""
RecoveryPolicy: 把 AgentFailure 映射为最终 RecoveryAction。

与 ErrorClassifier 的分工（DD-W4-D3-01 方案 B）：
- Classifier 产出 recommended_recovery —— "建议"（数据表，可能被误维护）
- RecoveryPolicy 输出最终决策 —— "权威"（硬编码安全规则）

纵深防御：即使 _SIGNALS 表被误改，Policy 依然拦截安全类错误。
只决策，不执行——不 sleep、不 retry、不调用外部组件。
"""
from __future__ import annotations

from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    RecoveryAction,
)


class RecoveryPolicy:
    """AgentFailure → RecoveryAction 的最终决策器。

    用法：
        policy = RecoveryPolicy()
        action = policy.decide(failure)
        # Orchestrator 拿到 action 后自行执行
    """

    def decide(self, failure: AgentFailure) -> RecoveryAction:
        """对一次失败给出最终恢复动作。

        规则顺序（越靠前越权威）：
        ① SECURITY 类别 → 硬编码 STOP
           不随 attempt 改变、不随 recommended 改变（T14）
        ② USER_INTERRUPT → PAUSE（I6，day3 §四十五）
        ③ 一致性守卫：retryable=False 但建议 RETRY → STOP
           （防御 classifier 表被误改，I1/I2 的第二道防线）
        ④ 其余 → 透传 classifier 的建议（方案 B）
        """
        # ① 安全类：Fail Closed，无任何例外（day3 §四十~四十一）
        if failure.category == ErrorCategory.SECURITY:
            return RecoveryAction.STOP

        # ② 用户中断：暂停而非失败（day3 §四十五）
        if failure.code == AgentErrorCode.USER_INTERRUPT:
            return RecoveryAction.PAUSE

        # ③ 一致性守卫：自相矛盾的失败不重试
        #    例：classifier 表误把 AUTH_FAILED 配成 RETRY，
        #    但 retryable=False —— Policy 拦截为 STOP
        if (
            failure.recommended_recovery == RecoveryAction.RETRY
            and not failure.retryable
        ):
            return RecoveryAction.STOP

        # ④ 透传建议（方案 B：第一版策略简单，执行仍在 Orchestrator）
        return failure.recommended_recovery