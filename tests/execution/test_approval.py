from __future__ import annotations

import pytest

from codeteam.events import AgentEventType
from codeteam.execution.approval import ApprovalManager
from codeteam.execution.models import (
    ApprovalDecision,
    ApprovalGrant,
    ApprovalScope,
    CommandRequest,
    PolicyDecision,
    PolicyEvaluation,
    RiskCategory,
)


def _request(
    tmp_path,
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


def _approval_evaluation() -> PolicyEvaluation:
    return PolicyEvaluation(
        decision=PolicyDecision.REQUIRE_APPROVAL,
        risks=(RiskCategory.NETWORK,),
        reasons=("Network command requires approval.",),
        matched_rules=("network",),
    )


def test_require_approval_creates_request_and_audit_event(tmp_path) -> None:
    manager = ApprovalManager()
    command = _request(tmp_path)

    approval = manager.create_request(command, _approval_evaluation())

    assert approval.task_id == "task-1"
    assert approval.agent_id == "agent-1"
    assert approval.command_fingerprint == command.fingerprint()
    assert approval.risks == (RiskCategory.NETWORK,)

    event = manager.events[-1]
    assert event.event_type is AgentEventType.APPROVAL_REQUESTED
    assert event.data["approval_id"] == approval.approval_id
    assert event.data["task_id"] == "task-1"
    assert event.data["agent_id"] == "agent-1"
    assert event.data["command_fingerprint"] == command.fingerprint()
    assert event.data["scope"] == ApprovalScope.ONCE.value
    assert event.data["risks"] == [RiskCategory.NETWORK.value]
    assert "argv" not in event.data
    assert "SECRET" not in str(event.data)


def test_once_scope_consumes_only_once(tmp_path) -> None:
    manager = ApprovalManager()
    command = _request(tmp_path)
    approval = manager.create_request(command, _approval_evaluation())
    grant = manager.approve(approval.approval_id, scope=ApprovalScope.ONCE)

    consumed = manager.consume(command, grant)
    assert consumed is not None
    assert consumed.is_consumed is True

    assert manager.consume(command, consumed) is None
    assert [
        event.event_type for event in manager.events
    ].count(AgentEventType.APPROVAL_CONSUMED) == 1


def test_task_scope_does_not_cross_task_or_agent(tmp_path) -> None:
    manager = ApprovalManager()
    command = _request(tmp_path)
    approval = manager.create_request(command, _approval_evaluation())
    grant = manager.approve(approval.approval_id, scope=ApprovalScope.TASK)

    same_command = _request(tmp_path)
    other_task = _request(tmp_path, task_id="task-2")
    other_agent = _request(tmp_path, agent_id="agent-2")

    assert manager.is_authorized(same_command, grant) is True
    assert manager.is_authorized(other_task, grant) is False
    assert manager.is_authorized(other_agent, grant) is False


def test_fingerprint_mismatch_rejects_grant(tmp_path) -> None:
    manager = ApprovalManager()
    command = _request(tmp_path)
    approval = manager.create_request(command, _approval_evaluation())
    grant = manager.approve(approval.approval_id, scope=ApprovalScope.TASK)

    modified = _request(tmp_path, argv=("curl", "https://evil.example"))

    assert modified.fingerprint() != command.fingerprint()
    assert manager.consume(modified, grant) is None


def test_deny_does_not_create_usable_grant(tmp_path) -> None:
    manager = ApprovalManager()
    command = _request(tmp_path)
    approval = manager.create_request(command, _approval_evaluation())

    manager.deny(approval.approval_id)

    with pytest.raises(ValueError):
        manager.approve(approval.approval_id)

    denied_grant = ApprovalGrant(
        approval_id=approval.approval_id,
        command_fingerprint=approval.command_fingerprint,
        task_id=approval.task_id,
        agent_id=approval.agent_id,
        scope=ApprovalScope.ONCE,
        decision=ApprovalDecision.DENIED,
        created_at=approval.created_at,
    )
    assert manager.consume(command, denied_grant) is None
    assert manager.events[-1].event_type is AgentEventType.APPROVAL_DENIED
