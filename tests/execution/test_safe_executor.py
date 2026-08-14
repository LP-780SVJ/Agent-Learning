from __future__ import annotations

from pathlib import Path

from codeteam.execution.approval import ApprovalManager
from codeteam.execution.models import (
    ApprovalScope,
    CommandRequest,
    CommandResult,
    CommandStatus,
    PolicyDecision,
    PolicyEvaluation,
    RiskCategory,
)
from codeteam.execution.safe_executor import SafeCommandExecutor


class FakePolicy:
    def __init__(self, evaluation: PolicyEvaluation) -> None:
        self.evaluation = evaluation

    def evaluate(self, request: CommandRequest) -> PolicyEvaluation:
        return self.evaluation


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request: CommandRequest) -> CommandResult:
        self.calls += 1
        return CommandResult(
            status=CommandStatus.SUCCESS,
            argv=request.argv,
            cwd=request.cwd,
            stdout="ok",
        )


def _request(
    tmp_path: Path,
    *,
    argv: tuple[str, ...] = ("curl", "https://example.com"),
    task_id: str = "task-1",
    agent_id: str | None = "agent-1",
) -> CommandRequest:
    return CommandRequest(
        argv=argv,
        cwd=tmp_path,
        workspace_root=tmp_path,
        task_id=task_id,
        agent_id=agent_id,
    )


def _evaluation(decision: PolicyDecision) -> PolicyEvaluation:
    return PolicyEvaluation(
        decision=decision,
        risks=(RiskCategory.NETWORK,),
        reasons=("network command",),
        matched_rules=("network",),
    )


def test_deny_does_not_call_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    executor = SafeCommandExecutor(
        policy=FakePolicy(_evaluation(PolicyDecision.DENY)),
        runner=runner,
    )

    result = executor.execute(_request(tmp_path))

    assert result.status is CommandStatus.POLICY_DENIED
    assert result.policy_decision is PolicyDecision.DENY
    assert runner.calls == 0


def test_require_approval_without_grant_returns_id_and_skips_runner(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executor = SafeCommandExecutor(
        policy=FakePolicy(_evaluation(PolicyDecision.REQUIRE_APPROVAL)),
        approval_manager=ApprovalManager(),
        runner=runner,
    )

    result = executor.execute(_request(tmp_path))

    assert result.status is CommandStatus.APPROVAL_REQUIRED
    assert result.approval_id is not None
    assert runner.calls == 0


def test_invalid_grant_does_not_call_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    manager = ApprovalManager()
    evaluation = _evaluation(PolicyDecision.REQUIRE_APPROVAL)
    executor = SafeCommandExecutor(
        policy=FakePolicy(evaluation),
        approval_manager=manager,
        runner=runner,
    )
    request = _request(tmp_path)
    other = _request(tmp_path, task_id="task-2")
    approval = manager.create_request(other, evaluation)
    grant = manager.approve(approval.approval_id, scope=ApprovalScope.ONCE)

    result = executor.execute(request, approval_grant=grant)

    assert result.status is CommandStatus.APPROVAL_DENIED
    assert runner.calls == 0


def test_approved_grant_calls_runner_once(tmp_path: Path) -> None:
    runner = FakeRunner()
    manager = ApprovalManager()
    evaluation = _evaluation(PolicyDecision.REQUIRE_APPROVAL)
    executor = SafeCommandExecutor(
        policy=FakePolicy(evaluation),
        approval_manager=manager,
        runner=runner,
    )
    request = _request(tmp_path)
    approval = manager.create_request(request, evaluation)
    grant = manager.approve(approval.approval_id, scope=ApprovalScope.ONCE)

    result = executor.execute(request, approval_grant=grant)

    assert result.status is CommandStatus.SUCCESS
    assert runner.calls == 1


def test_modified_request_cannot_reuse_old_approval(tmp_path: Path) -> None:
    runner = FakeRunner()
    manager = ApprovalManager()
    evaluation = _evaluation(PolicyDecision.REQUIRE_APPROVAL)
    executor = SafeCommandExecutor(
        policy=FakePolicy(evaluation),
        approval_manager=manager,
        runner=runner,
    )
    request = _request(tmp_path)
    approval = manager.create_request(request, evaluation)
    grant = manager.approve(approval.approval_id, scope=ApprovalScope.TASK)
    modified = _request(tmp_path, argv=("curl", "https://evil.example"))

    result = executor.execute(modified, approval_grant=grant)

    assert result.status is CommandStatus.APPROVAL_DENIED
    assert runner.calls == 0


def test_allow_decision_calls_runner_directly(tmp_path: Path) -> None:
    runner = FakeRunner()
    executor = SafeCommandExecutor(
        policy=FakePolicy(_evaluation(PolicyDecision.ALLOW)),
        runner=runner,
    )

    result = executor.execute(_request(tmp_path, argv=("python", "--version")))

    assert result.status is CommandStatus.SUCCESS
    assert result.policy_decision is PolicyDecision.ALLOW
    assert runner.calls == 1
