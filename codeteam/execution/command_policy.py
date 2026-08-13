from __future__ import annotations

from codeteam.execution.models import (
    CommandRequest,
    PolicyDecision,
    PolicyEvaluation,
    RiskCategory,
    RuleResult,
)
from codeteam.execution.policy_rules import (
    CredentialPathRule,
    CwdWorkspaceRule,
    DockerPrivilegeRule,
    FilesystemEscapeRule,
    GitDestructiveRule,
    NetworkCommandRule,
    PolicyRule,
    PrivilegeEscalationRule,
    RemoteWriteRule,
    SafeDevCommandRule,
    SafeGitReadRule,
    ShellInterpreterRule,
    SystemControlRule,
)

_DECISION_PRIORITY = {
    PolicyDecision.ALLOW: 0,
    PolicyDecision.ALLOW_SANDBOXED: 1,
    PolicyDecision.REQUIRE_APPROVAL: 2,
    PolicyDecision.DENY: 3,
}


class CommandPolicy:
    def __init__(
        self,
        rules: list[PolicyRule],
    ) -> None:
        self.rules = list(rules)

    @classmethod
    def default(cls) -> CommandPolicy:
        return cls(
            rules=[
                CwdWorkspaceRule(),
                PrivilegeEscalationRule(),
                SystemControlRule(),
                GitDestructiveRule(),
                ShellInterpreterRule(),
                FilesystemEscapeRule(),
                CredentialPathRule(),
                DockerPrivilegeRule(),
                RemoteWriteRule(),
                NetworkCommandRule(),
                SafeDevCommandRule(),
                SafeGitReadRule(),
            ]
        )

    def evaluate(
        self,
        request: CommandRequest,
    ) -> PolicyEvaluation:
        results: list[RuleResult] = []

        for rule in self.rules:
            result = rule.evaluate(request)
            if result is not None:
                results.append(result)

        if not results:
            return PolicyEvaluation(
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.UNKNOWN,),
                reasons=("Unknown command requires approval.",),
                matched_rules=(),
            )

        final_result = max(
            results,
            key=lambda result: _DECISION_PRIORITY[result.decision],
        )

        risks = tuple(
            dict.fromkeys(
                risk
                for result in results
                for risk in result.risks
            )
        )

        reasons = tuple(result.reason for result in results)
        matched_rules = tuple(result.rule_name for result in results)

        return PolicyEvaluation(
            decision=final_result.decision,
            risks=risks,
            reasons=reasons,
            matched_rules=matched_rules,
        )
