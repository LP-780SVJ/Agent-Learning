from __future__ import annotations

from codeteam.execution.approval import ApprovalManager
from codeteam.execution.command_policy import CommandPolicy
from codeteam.execution.models import (
    ApprovalGrant,
    CommandRequest,
    CommandResult,
    CommandStatus,
    PolicyDecision,
)
from codeteam.execution.runner import CommandRunner


class SafeCommandExecutor:
    def __init__(
        self,
        *,
        policy: CommandPolicy | None = None,
        approval_manager: ApprovalManager | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        self._policy = policy or CommandPolicy.default()
        self._approval_manager = approval_manager or ApprovalManager()
        self._runner = runner or CommandRunner()

    def execute(
        self,
        request: CommandRequest,
        *,
        approval_grant: ApprovalGrant | None = None,
    ) -> CommandResult:
        evaluation = self._policy.evaluate(request)

        if evaluation.decision is PolicyDecision.DENY:
            return CommandResult(
                status=CommandStatus.POLICY_DENIED,
                argv=request.argv,
                cwd=request.cwd,
                policy_decision=evaluation.decision,
                reasons=evaluation.reasons,
                error="Command denied by policy.",
            )

        if evaluation.decision is PolicyDecision.REQUIRE_APPROVAL:
            if approval_grant is None:
                approval_request = self._approval_manager.create_request(
                    request,
                    evaluation,
                )
                return CommandResult(
                    status=CommandStatus.APPROVAL_REQUIRED,
                    argv=request.argv,
                    cwd=request.cwd,
                    policy_decision=evaluation.decision,
                    approval_id=approval_request.approval_id,
                    reasons=evaluation.reasons,
                    error="Command requires approval.",
                )

            consumed = self._approval_manager.consume(request, approval_grant)
            if consumed is None:
                return CommandResult(
                    status=CommandStatus.APPROVAL_DENIED,
                    argv=request.argv,
                    cwd=request.cwd,
                    policy_decision=evaluation.decision,
                    reasons=evaluation.reasons,
                    error="Approval grant is invalid for this command.",
                )

        result = self._runner.run(request)
        return result.model_copy(
            update={
                "policy_decision": evaluation.decision,
                "reasons": evaluation.reasons,
            }
        )