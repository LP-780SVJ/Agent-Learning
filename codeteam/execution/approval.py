from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from codeteam.events import AgentEvent, AgentEventType, make_event
from codeteam.execution.models import (
    ApprovalDecision,
    ApprovalGrant,
    ApprovalRequest,
    ApprovalScope,
    CommandRequest,
    PolicyEvaluation,
    RiskCategory,
)


class ApprovalManager:
    """管理命令执行前的人工授权。
    
    字段说明：
    - _requests: 存储所有的授权请求，键为 approval_id
    - _grants: 存储所有的授权批准，键为 approval_id
    - _denied: 存储所有被拒绝的授权请求的 approval_id
    - _events: 复用 Week1 AgentEvent 列表，记录 approval audit
    - _lock: 用于线程安全的锁
    """

    def __init__(self, events: list[AgentEvent] | None = None) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._grants: dict[str, ApprovalGrant] = {}
        self._denied: set[str] = set()
        self._events = [] if events is None else events
        self._lock = Lock()

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        return tuple(self._events)

    def create_request(
        self,
        command: CommandRequest,
        evaluation: PolicyEvaluation,
        *,
        requested_scope: ApprovalScope = ApprovalScope.ONCE,
    ) -> ApprovalRequest:
        if command.task_id is None:
            raise ValueError("Approval requires command.task_id.")

        approval = ApprovalRequest(
            approval_id=f"approval-{uuid4().hex}",
            task_id=command.task_id,
            agent_id=command.agent_id,
            command_fingerprint=command.fingerprint(),
            argv=command.argv,
            cwd=command.cwd,
            workspace_root=command.workspace_root,
            risks=evaluation.risks,
            reasons=evaluation.reasons,
            requested_scope=requested_scope,
            created_at=datetime.now(timezone.utc),
        )

        with self._lock:
            self._requests[approval.approval_id] = approval
            self._record_event(
                AgentEventType.APPROVAL_REQUESTED,
                "Approval requested.",
                approval_id=approval.approval_id,
                task_id=approval.task_id,
                agent_id=approval.agent_id,
                command_fingerprint=approval.command_fingerprint,
                scope=approval.requested_scope,
                risks=approval.risks,
            )

        return approval

    def approve(
        self,
        approval_id: str,
        *,
        scope: ApprovalScope | None = None,
    ) -> ApprovalGrant:
        with self._lock:
            request = self._get_request(approval_id)
            if approval_id in self._denied:
                raise ValueError(f"Approval was denied: {approval_id}")
            grant = ApprovalGrant(
                approval_id=approval_id,
                command_fingerprint=request.command_fingerprint,
                task_id=request.task_id,
                agent_id=request.agent_id,
                scope=scope or request.requested_scope,
                decision=ApprovalDecision.APPROVED,
                created_at=datetime.now(timezone.utc),
            )
            self._grants[approval_id] = grant
            self._denied.discard(approval_id)
            self._record_event(
                AgentEventType.APPROVAL_APPROVED,
                "Approval approved.",
                approval_id=grant.approval_id,
                task_id=grant.task_id,
                agent_id=grant.agent_id,
                command_fingerprint=grant.command_fingerprint,
                scope=grant.scope,
                decision=grant.decision,
                risks=request.risks,
            )
            return grant

    def deny(self, approval_id: str) -> None:
        with self._lock:
            request = self._get_request(approval_id)
            self._grants.pop(approval_id, None)
            self._denied.add(approval_id)
            self._record_event(
                AgentEventType.APPROVAL_DENIED,
                "Approval denied.",
                approval_id=request.approval_id,
                task_id=request.task_id,
                agent_id=request.agent_id,
                command_fingerprint=request.command_fingerprint,
                scope=request.requested_scope,
                decision=ApprovalDecision.DENIED,
                risks=request.risks,
            )

    def is_authorized(
        self,
        command: CommandRequest,
        grant: ApprovalGrant,
    ) -> bool:
        return self._matching_grant(command, grant) is not None

    def consume(
        self,
        command: CommandRequest,
        grant: ApprovalGrant,
    ) -> ApprovalGrant | None:
        with self._lock:
            current = self._grants.get(grant.approval_id)
            matched = self._matching_grant(command, current)
            if matched is None:
                return None

            if matched.scope is ApprovalScope.ONCE:
                consumed = matched.model_copy(
                    update={"consumed_at": datetime.now(timezone.utc)}
                )
                self._grants[matched.approval_id] = consumed
                self._record_consumed(consumed)
                return consumed

            self._record_consumed(matched)
            return matched

    def _get_request(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError as error:
            raise ValueError(f"Unknown approval_id: {approval_id}") from error

    def _matching_grant(
        self,
        command: CommandRequest,
        grant: ApprovalGrant | None,
    ) -> ApprovalGrant | None:
        if grant is None:
            return None

        if grant.decision is not ApprovalDecision.APPROVED:
            return None

        if grant.task_id != command.task_id:
            return None

        if grant.agent_id != command.agent_id:
            return None

        if grant.command_fingerprint != command.fingerprint():
            return None

        if grant.scope is ApprovalScope.ONCE and grant.is_consumed:
            return None

        return grant

    def _record_consumed(self, grant: ApprovalGrant) -> None:
        request = self._requests.get(grant.approval_id)
        self._record_event(
            AgentEventType.APPROVAL_CONSUMED,
            "Approval consumed.",
            approval_id=grant.approval_id,
            task_id=grant.task_id,
            agent_id=grant.agent_id,
            command_fingerprint=grant.command_fingerprint,
            scope=grant.scope,
            decision=grant.decision,
            risks=() if request is None else request.risks,
        )

    def _record_event(
        self,
        event_type: AgentEventType,
        message: str,
        *,
        approval_id: str,
        task_id: str,
        agent_id: str | None,
        command_fingerprint: str,
        scope: ApprovalScope | None = None,
        decision: ApprovalDecision | None = None,
        risks: tuple[RiskCategory, ...] = (),
    ) -> None:
        self._events.append(
            make_event(
                event_type,
                message,
                data={
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "command_fingerprint": command_fingerprint,
                    "scope": None if scope is None else scope.value,
                    "decision": None if decision is None else decision.value,
                    "risks": [risk.value for risk in risks],
                    "actor": "user",
                },
            )
        )
