from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from codeteam.execution.approval import ApprovalManager
from codeteam.execution.command_policy import CommandPolicy
from codeteam.execution.models import (
    ApprovalGrant,
    CommandRequest,
    CommandResult,
    CommandStatus,
    PolicyDecision,
    PolicyEvaluation,
)
from codeteam.git.checkpoint import CheckpointManager
from codeteam.git.models import Checkpoint, CheckpointReason, GitDiff, PatchResult
from codeteam.git.workspace import GitWorkspace
from codeteam.sandbox.docker_runner import DockerRunner
from codeteam.sandbox.models import SandboxExecutionContext, SandboxProfile


class SafeExecutionLane(str, Enum):
    COMMAND = "command"
    PATCH = "patch"


class SafeExecutionStatus(str, Enum):
    POLICY_FAILED = "policy_failed"
    POLICY_DENIED = "policy_denied"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_FAILED = "approval_failed"
    SANDBOX_FAILED = "sandbox_failed"
    CHECKPOINT_FAILED = "checkpoint_failed"
    PATCH_FAILED = "patch_failed"
    COMPLETED = "completed"


class SafeExecutionAuditRecord(BaseModel):
    event: str
    correlation_id: str
    lane: SafeExecutionLane
    task_id: str | None = None
    request_fingerprint: str | None = None
    policy_decision: PolicyDecision | None = None
    approval_id: str | None = None
    sandbox_required: bool | None = None
    checkpoint_id: str | None = None
    status: SafeExecutionStatus | None = None
    message: str | None = None


class SafeCommandExecutionRequest(BaseModel):
    command: CommandRequest
    sandbox_profile: SandboxProfile = Field(default_factory=SandboxProfile)
    approval_grant: ApprovalGrant | None = None
    correlation_id: str = Field(default_factory=lambda: f"exec-{uuid4().hex}")


class SafePatchExecutionRequest(BaseModel):
    patch: str
    workspace_root: Path
    checkpoint_state_root: Path
    task_id: str
    agent_id: str | None = None
    correlation_id: str = Field(default_factory=lambda: f"exec-{uuid4().hex}")


class SafeExecutionResult(BaseModel):
    lane: SafeExecutionLane
    status: SafeExecutionStatus
    correlation_id: str
    task_id: str | None = None
    request_fingerprint: str | None = None
    policy_evaluation: PolicyEvaluation | None = None
    sandbox_required: bool = False
    approval_invoked: bool = False
    sandbox_invoked: bool = False
    approval_id: str | None = None
    command_result: CommandResult | None = None
    checkpoint: Checkpoint | None = None
    patch_result: PatchResult | None = None
    diff: GitDiff | None = None
    audit: tuple[SafeExecutionAuditRecord, ...] = ()
    error: str | None = None


PolicyFactory = Callable[[], CommandPolicy]
ApprovalFactory = Callable[[], ApprovalManager]
SandboxRunnerFactory = Callable[[], DockerRunner]
GitWorkspaceFactory = Callable[[Path], GitWorkspace]
CheckpointManagerFactory = Callable[[Path, Path, str], CheckpointManager]


class SafeExecutionService:
    """Day7 unified safety entrypoint for side-effectful execution.

    V1 only implements the Command Lane. Patch Lane is intentionally left out
    until checkpoint + GitWorkspace integration can be wired with tests.
    """

    def __init__(
        self,
        *,
        policy: CommandPolicy | None = None,
        approval_manager: ApprovalManager | None = None,
        sandbox_runner: DockerRunner | None = None,
        git_workspace_factory: GitWorkspaceFactory | None = None,
        checkpoint_manager_factory: CheckpointManagerFactory | None = None,
    ) -> None:
        self._policy = policy or CommandPolicy.default()
        self._approval_manager = approval_manager or ApprovalManager()
        self._sandbox_runner = sandbox_runner or DockerRunner()
        self._git_workspace_factory = git_workspace_factory or GitWorkspace
        self._checkpoint_manager_factory = (
            checkpoint_manager_factory or CheckpointManager
        )

    def execute_command(
        self,
        request: SafeCommandExecutionRequest,
    ) -> SafeExecutionResult:
        command = request.command
        audit = self._new_audit(
            request.correlation_id,
            SafeExecutionLane.COMMAND,
            task_id=command.task_id,
            request_fingerprint=command.fingerprint(),
        )
        audit.append("request.received")

        try:
            evaluation = self._policy.evaluate(command)
        except Exception as error:  # noqa: BLE001
            audit.append(
                "policy.failed",
                status=SafeExecutionStatus.POLICY_FAILED,
                message=str(error),
            )
            return self._command_terminal_result(
                command,
                None,
                correlation_id=request.correlation_id,
                audit=audit.records,
                status=SafeExecutionStatus.POLICY_FAILED,
                command_status=CommandStatus.POLICY_DENIED,
                error=f"Policy evaluation failed closed: {error}",
            )

        audit.append(
            "policy.evaluated",
            policy_decision=evaluation.decision,
            message="Command policy evaluated.",
        )

        if evaluation.decision is PolicyDecision.DENY:
            audit.append(
                "policy.denied",
                policy_decision=evaluation.decision,
                status=SafeExecutionStatus.POLICY_DENIED,
            )
            return self._command_terminal_result(
                command,
                evaluation,
                correlation_id=request.correlation_id,
                audit=audit.records,
                status=SafeExecutionStatus.POLICY_DENIED,
                command_status=CommandStatus.POLICY_DENIED,
                error="Command denied by policy.",
            )

        if evaluation.decision is PolicyDecision.REQUIRE_APPROVAL:
            approval_result = self._handle_approval(request, evaluation, audit)
            if approval_result is not None:
                return approval_result

        return self._execute_in_sandbox(request, evaluation, audit)

    def execute_patch(
        self,
        request: SafePatchExecutionRequest,
    ) -> SafeExecutionResult:
        patch_fingerprint = f"patch-{uuid4().hex}"
        audit = self._new_audit(
            request.correlation_id,
            SafeExecutionLane.PATCH,
            task_id=request.task_id,
            request_fingerprint=patch_fingerprint,
        )
        audit.append("request.received")

        try:
            checkpoint_manager = self._checkpoint_manager_factory(
                request.workspace_root,
                request.checkpoint_state_root,
                request.task_id,
            )
            checkpoint = checkpoint_manager.create(CheckpointReason.BEFORE_TOOL)
        except Exception as error:  # noqa: BLE001
            audit.append(
                "checkpoint.failed",
                status=SafeExecutionStatus.CHECKPOINT_FAILED,
                message=str(error),
            )
            return SafeExecutionResult(
                lane=SafeExecutionLane.PATCH,
                status=SafeExecutionStatus.CHECKPOINT_FAILED,
                correlation_id=request.correlation_id,
                task_id=request.task_id,
                request_fingerprint=patch_fingerprint,
                audit=audit.records,
                error=f"Checkpoint creation failed closed: {error}",
            )

        audit.append(
            "checkpoint.created",
            checkpoint_id=checkpoint.checkpoint_id,
            message="Checkpoint created before patch side effect.",
        )

        try:
            workspace = self._git_workspace_factory(request.workspace_root)
            patch_result = workspace.apply_patch(request.patch)
            diff = workspace.diff()
        except Exception as error:  # noqa: BLE001
            audit.append(
                "patch.failed",
                checkpoint_id=checkpoint.checkpoint_id,
                status=SafeExecutionStatus.PATCH_FAILED,
                message=str(error),
            )
            return SafeExecutionResult(
                lane=SafeExecutionLane.PATCH,
                status=SafeExecutionStatus.PATCH_FAILED,
                correlation_id=request.correlation_id,
                task_id=request.task_id,
                request_fingerprint=patch_fingerprint,
                checkpoint=checkpoint,
                audit=audit.records,
                error=f"Patch execution failed: {error}",
            )

        status = (
            SafeExecutionStatus.COMPLETED
            if patch_result.applied
            else SafeExecutionStatus.PATCH_FAILED
        )
        audit.append(
            "patch.completed",
            checkpoint_id=checkpoint.checkpoint_id,
            status=status,
            message="Patch lane completed.",
        )

        return SafeExecutionResult(
            lane=SafeExecutionLane.PATCH,
            status=status,
            correlation_id=request.correlation_id,
            task_id=request.task_id,
            request_fingerprint=patch_fingerprint,
            checkpoint=checkpoint,
            patch_result=patch_result,
            diff=diff,
            audit=audit.records,
            error=patch_result.failure_reason if not patch_result.applied else None,
        )

    def _handle_approval(
        self,
        request: SafeCommandExecutionRequest,
        evaluation: PolicyEvaluation,
        audit: _AuditBuilder,
    ) -> SafeExecutionResult | None:
        command = request.command

        if request.approval_grant is None:
            try:
                approval_request = self._approval_manager.create_request(
                    command,
                    evaluation,
                )
            except Exception as error:  # noqa: BLE001
                audit.append(
                    "approval.failed",
                    policy_decision=evaluation.decision,
                    status=SafeExecutionStatus.APPROVAL_FAILED,
                    message=str(error),
                )
                return self._command_terminal_result(
                    command,
                    evaluation,
                    correlation_id=request.correlation_id,
                    audit=audit.records,
                    status=SafeExecutionStatus.APPROVAL_FAILED,
                    command_status=CommandStatus.APPROVAL_DENIED,
                    error=f"Approval request failed closed: {error}",
                )
            audit.append(
                "approval.requested",
                policy_decision=evaluation.decision,
                approval_id=approval_request.approval_id,
            )
            return self._command_terminal_result(
                command,
                evaluation,
                correlation_id=request.correlation_id,
                audit=audit.records,
                status=SafeExecutionStatus.APPROVAL_REQUIRED,
                command_status=CommandStatus.APPROVAL_REQUIRED,
                approval_id=approval_request.approval_id,
                error="Command requires approval.",
            )

        try:
            consumed = self._approval_manager.consume(
                command,
                request.approval_grant,
            )
        except Exception as error:  # noqa: BLE001
            audit.append(
                "approval.failed",
                policy_decision=evaluation.decision,
                approval_id=request.approval_grant.approval_id,
                status=SafeExecutionStatus.APPROVAL_FAILED,
                message=str(error),
            )
            return self._command_terminal_result(
                command,
                evaluation,
                correlation_id=request.correlation_id,
                audit=audit.records,
                status=SafeExecutionStatus.APPROVAL_FAILED,
                command_status=CommandStatus.APPROVAL_DENIED,
                error=f"Approval consume failed closed: {error}",
            )

        if consumed is None:
            audit.append(
                "approval.denied",
                policy_decision=evaluation.decision,
                approval_id=request.approval_grant.approval_id,
                status=SafeExecutionStatus.APPROVAL_DENIED,
            )
            return self._command_terminal_result(
                command,
                evaluation,
                correlation_id=request.correlation_id,
                audit=audit.records,
                status=SafeExecutionStatus.APPROVAL_DENIED,
                command_status=CommandStatus.APPROVAL_DENIED,
                error="Approval grant is invalid for this command.",
            )

        audit.append(
            "approval.consumed",
            policy_decision=evaluation.decision,
            approval_id=consumed.approval_id,
        )
        return None

    def _execute_in_sandbox(
        self,
        request: SafeCommandExecutionRequest,
        evaluation: PolicyEvaluation,
        audit: _AuditBuilder,
    ) -> SafeExecutionResult:
        command = request.command

        try:
            audit.append(
                "sandbox.starting",
                policy_decision=evaluation.decision,
                sandbox_required=True,
            )
            context = SandboxExecutionContext(
                argv=command.argv,
                workspace_root=command.workspace_root,
                cwd=command.cwd,
                profile=request.sandbox_profile,
            )
            command_result = self._sandbox_runner.run(context)
        except Exception as error:  # noqa: BLE001
            return SafeExecutionResult(
                lane=SafeExecutionLane.COMMAND,
                status=SafeExecutionStatus.SANDBOX_FAILED,
                correlation_id=request.correlation_id,
                task_id=command.task_id,
                request_fingerprint=command.fingerprint(),
                policy_evaluation=evaluation,
                sandbox_required=True,
                approval_invoked=PolicyDecision.REQUIRE_APPROVAL is evaluation.decision,
                sandbox_invoked=False,
                command_result=CommandResult(
                    status=CommandStatus.START_FAILED,
                    argv=command.argv,
                    cwd=command.cwd,
                    policy_decision=evaluation.decision,
                    reasons=evaluation.reasons,
                    error=f"Sandbox setup failed: {error}",
                ),
                audit=(
                    *audit.records,
                    self._audit_record(
                        request.correlation_id,
                        SafeExecutionLane.COMMAND,
                        "sandbox.failed",
                        task_id=command.task_id,
                        request_fingerprint=command.fingerprint(),
                        policy_decision=evaluation.decision,
                        sandbox_required=True,
                        status=SafeExecutionStatus.SANDBOX_FAILED,
                        message=str(error),
                    ),
                ),
                error=f"Sandbox setup failed: {error}",
            )

        status = (
            SafeExecutionStatus.SANDBOX_FAILED
            if _looks_like_sandbox_backend_failure(command_result)
            else SafeExecutionStatus.COMPLETED
        )

        audit.append(
            "command.completed",
            policy_decision=evaluation.decision,
            sandbox_required=True,
            status=status,
            message="Sandbox command completed.",
        )

        return SafeExecutionResult(
            lane=SafeExecutionLane.COMMAND,
            status=status,
            correlation_id=request.correlation_id,
            task_id=command.task_id,
            request_fingerprint=command.fingerprint(),
            policy_evaluation=evaluation,
            sandbox_required=True,
            approval_invoked=PolicyDecision.REQUIRE_APPROVAL is evaluation.decision,
            sandbox_invoked=True,
            command_result=command_result.model_copy(
                update={
                    "policy_decision": evaluation.decision,
                    "reasons": evaluation.reasons,
                }
            ),
            audit=audit.records,
            error=command_result.error if status is SafeExecutionStatus.SANDBOX_FAILED else None,
        )

    def _command_terminal_result(
        self,
        command: CommandRequest,
        evaluation: PolicyEvaluation | None,
        *,
        correlation_id: str,
        audit: tuple[SafeExecutionAuditRecord, ...],
        status: SafeExecutionStatus,
        command_status: CommandStatus,
        approval_id: str | None = None,
        error: str,
    ) -> SafeExecutionResult:
        return SafeExecutionResult(
            lane=SafeExecutionLane.COMMAND,
            status=status,
            correlation_id=correlation_id,
            task_id=command.task_id,
            request_fingerprint=command.fingerprint(),
            policy_evaluation=evaluation,
            sandbox_required=False,
            approval_invoked=status in {
                SafeExecutionStatus.APPROVAL_REQUIRED,
                SafeExecutionStatus.APPROVAL_DENIED,
                SafeExecutionStatus.APPROVAL_FAILED,
            },
            sandbox_invoked=False,
            approval_id=approval_id,
            command_result=CommandResult(
                status=command_status,
                argv=command.argv,
                cwd=command.cwd,
                policy_decision=None if evaluation is None else evaluation.decision,
                approval_id=approval_id,
                reasons=() if evaluation is None else evaluation.reasons,
                error=error,
            ),
            audit=audit,
            error=error,
        )

    def _new_audit(
        self,
        correlation_id: str,
        lane: SafeExecutionLane,
        *,
        task_id: str | None,
        request_fingerprint: str | None,
    ) -> _AuditBuilder:
        return _AuditBuilder(
            correlation_id=correlation_id,
            lane=lane,
            task_id=task_id,
            request_fingerprint=request_fingerprint,
        )

    def _audit_record(
        self,
        correlation_id: str,
        lane: SafeExecutionLane,
        event: str,
        **kwargs: Any,
    ) -> SafeExecutionAuditRecord:
        return SafeExecutionAuditRecord(
            event=event,
            correlation_id=correlation_id,
            lane=lane,
            **kwargs,
        )


class _AuditBuilder:
    def __init__(
        self,
        *,
        correlation_id: str,
        lane: SafeExecutionLane,
        task_id: str | None,
        request_fingerprint: str | None,
    ) -> None:
        self._correlation_id = correlation_id
        self._lane = lane
        self._task_id = task_id
        self._request_fingerprint = request_fingerprint
        self._records: list[SafeExecutionAuditRecord] = []

    @property
    def records(self) -> tuple[SafeExecutionAuditRecord, ...]:
        return tuple(self._records)

    def append(
        self,
        event: str,
        **kwargs: Any,
    ) -> None:
        self._records.append(
            SafeExecutionAuditRecord(
                event=event,
                correlation_id=self._correlation_id,
                lane=self._lane,
                task_id=kwargs.pop("task_id", self._task_id),
                request_fingerprint=kwargs.pop(
                    "request_fingerprint",
                    self._request_fingerprint,
                ),
                **kwargs,
            )
        )


def _looks_like_sandbox_backend_failure(result: CommandResult) -> bool:
    if result.status is CommandStatus.START_FAILED:
        return True

    combined_output = " ".join(
        value.lower()
        for value in (result.error, result.stderr, result.stdout)
        if value
    )
    backend_failure_markers = (
        "cannot connect to the docker daemon",
        "permission denied while trying to connect to the docker api",
        "docker daemon",
        "no such image",
        "pull access denied",
        "image pull",
        "not found locally and pull policy is never",
    )
    return any(marker in combined_output for marker in backend_failure_markers)
