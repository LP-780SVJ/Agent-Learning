from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import Callable
from enum import Enum
from threading import Lock

from pydantic import BaseModel, Field, field_validator

from codeteam.agent_team.models import AgentIdentity
from codeteam.events import AgentEvent, AgentEventType, make_event


class AgentMessageType(str, Enum):
    TASK_ASSIGNED = "task_assigned"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    REVIEW_FINDING = "review_finding"
    REQUEST_HELP = "request_help"
    INFO = "info"
    SHUTDOWN_REQUESTED = "shutdown_requested"


class AgentMessage(BaseModel):
    message_id: str
    sender_id: str
    recipient_id: str
    message_type: AgentMessageType
    task_id: str
    node_id: str | None = None
    correlation_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

    @field_validator(
        "message_id",
        "sender_id",
        "recipient_id",
        "task_id",
        "correlation_id",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message fields must not be blank")
        return stripped

    @field_validator("node_id")
    @classmethod
    def _blank_node_id_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        return stripped


class MailboxError(Exception):
    """Base class for Agent mailbox errors."""


class UnknownAgentError(MailboxError):
    """Raised when a sender or recipient has not registered an inbox."""


class DuplicateAgentError(MailboxError):
    """Raised when an agent id is registered more than once."""


class DuplicateMessageError(MailboxError):
    """Raised when a message id has already been accepted."""


class MailboxFullError(MailboxError):
    """Raised when the recipient inbox is at capacity."""


class InvalidMessageError(MailboxError):
    """Raised when a mailbox operation cannot build a valid message."""


EventSink = Callable[[AgentEvent], None]


class AgentMailbox:
    def __init__(
        self,
        *,
        capacity_per_inbox: int = 1000,
        event_sink: EventSink | None = None,
    ) -> None:
        if capacity_per_inbox < 1:
            raise ValueError("capacity_per_inbox must be >= 1")

        self._capacity_per_inbox = capacity_per_inbox
        self._lock = Lock()
        self._agents: dict[str, AgentIdentity] = {}
        self._inboxes: dict[str, deque[AgentMessage]] = {}
        self._seen_message_ids: set[str] = set()
        self._events: list[AgentEvent] = []
        self._event_sink = event_sink

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        with self._lock:
            return tuple(self._copy_event(event) for event in self._events)

    @property
    def registered_agents(self) -> tuple[AgentIdentity, ...]:
        with self._lock:
            return tuple(
                self._agents[agent_id].model_copy(deep=True)
                for agent_id in sorted(self._agents)
            )

    def queue_size(self, agent_id: str) -> int:
        with self._lock:
            self._require_agent_locked(agent_id)
            return len(self._inboxes[agent_id])

    def register_agent(self, identity: AgentIdentity) -> AgentIdentity:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            agent_id = identity.agent_id
            if agent_id in self._agents:
                raise DuplicateAgentError(agent_id)
            self._agents[agent_id] = identity.model_copy(deep=True)
            self._inboxes[agent_id] = deque()
            self._record_event_locked(
                pending_delivery,
                AgentEventType.MAILBOX_AGENT_REGISTERED,
                f"Agent {agent_id} registered mailbox.",
                sender_id=agent_id,
                recipient_id=agent_id,
                reason_code="agent_registered",
                queue_size=0,
            )
            result = self._agents[agent_id].model_copy(deep=True)
        self._deliver_events(pending_delivery)
        return result

    def send(self, message: AgentMessage) -> AgentMessage:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            self._require_agent_locked(message.sender_id)
            self._require_agent_locked(message.recipient_id)
            self._require_new_message_id_locked(message.message_id)
            self._require_capacity_locked(message.recipient_id)

            stored = message.model_copy(deep=True)
            self._inboxes[stored.recipient_id].append(stored)
            self._seen_message_ids.add(stored.message_id)
            queue_size = len(self._inboxes[stored.recipient_id])
            self._record_event_locked(
                pending_delivery,
                AgentEventType.MAILBOX_MESSAGE_SENT,
                f"Message {stored.message_id} sent.",
                message=stored,
                queue_size=queue_size,
            )
            result = stored.model_copy(deep=True)
        self._deliver_events(pending_delivery)
        return result

    def receive(self, agent_id: str) -> AgentMessage | None:
        pending_delivery: list[AgentEvent] = []
        with self._lock:
            self._require_agent_locked(agent_id)
            if not self._inboxes[agent_id]:
                return None
            message = self._inboxes[agent_id].popleft()
            queue_size = len(self._inboxes[agent_id])
            self._record_event_locked(
                pending_delivery,
                AgentEventType.MAILBOX_MESSAGE_RECEIVED,
                f"Message {message.message_id} received.",
                message=message,
                queue_size=queue_size,
            )
            result = message.model_copy(deep=True)
        self._deliver_events(pending_delivery)
        return result

    def broadcast(
        self,
        *,
        sender_id: str,
        recipient_ids: tuple[str, ...],
        message_type: AgentMessageType,
        task_id: str,
        node_id: str | None = None,
        payload: dict[str, object] | None = None,
        correlation_id: str | None = None,
    ) -> tuple[AgentMessage, ...]:
        if not recipient_ids:
            raise InvalidMessageError("recipient_ids must not be empty")
        if len(set(recipient_ids)) != len(recipient_ids):
            raise InvalidMessageError("recipient_ids must be unique")

        pending_delivery: list[AgentEvent] = []
        with self._lock:
            self._require_agent_locked(sender_id)
            for recipient_id in recipient_ids:
                self._require_agent_locked(recipient_id)
                self._require_capacity_locked(recipient_id)

            shared_correlation_id = correlation_id or f"corr-{uuid.uuid4().hex}"
            messages = tuple(
                AgentMessage(
                    message_id=f"msg-{uuid.uuid4().hex}",
                    sender_id=sender_id,
                    recipient_id=recipient_id,
                    message_type=message_type,
                    task_id=task_id,
                    node_id=node_id,
                    correlation_id=shared_correlation_id,
                    payload={} if payload is None else dict(payload),
                )
                for recipient_id in recipient_ids
            )
            for message in messages:
                self._require_new_message_id_locked(message.message_id)

            for message in messages:
                stored = message.model_copy(deep=True)
                self._inboxes[stored.recipient_id].append(stored)
                self._seen_message_ids.add(stored.message_id)

            for message in messages:
                self._record_event_locked(
                    pending_delivery,
                    AgentEventType.MAILBOX_BROADCAST_SENT,
                    f"Broadcast message {message.message_id} sent.",
                    message=message,
                    queue_size=len(self._inboxes[message.recipient_id]),
                    recipient_count=len(recipient_ids),
                )

            result = tuple(message.model_copy(deep=True) for message in messages)
        self._deliver_events(pending_delivery)
        return result

    def _require_agent_locked(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            raise UnknownAgentError(agent_id)

    def _require_new_message_id_locked(self, message_id: str) -> None:
        if message_id in self._seen_message_ids:
            raise DuplicateMessageError(message_id)

    def _require_capacity_locked(self, agent_id: str) -> None:
        if len(self._inboxes[agent_id]) >= self._capacity_per_inbox:
            raise MailboxFullError(agent_id)

    def _record_event_locked(
        self,
        pending_delivery: list[AgentEvent],
        event_type: AgentEventType,
        message_text: str,
        *,
        message: AgentMessage | None = None,
        sender_id: str | None = None,
        recipient_id: str | None = None,
        queue_size: int,
        reason_code: str | None = None,
        recipient_count: int | None = None,
    ) -> None:
        data: dict[str, object] = {"queue_size": queue_size}
        if message is not None:
            data.update(
                {
                    "message_id": message.message_id,
                    "sender_id": message.sender_id,
                    "recipient_id": message.recipient_id,
                    "message_type": message.message_type.value,
                    "task_id": message.task_id,
                    "correlation_id": message.correlation_id,
                }
            )
            if message.node_id is not None:
                data["node_id"] = message.node_id
        else:
            if sender_id is not None:
                data["sender_id"] = sender_id
            if recipient_id is not None:
                data["recipient_id"] = recipient_id
        if reason_code is not None:
            data["reason_code"] = reason_code
        if recipient_count is not None:
            data["recipient_count"] = recipient_count

        event = make_event(event_type, message_text, data=data)
        self._events.append(event)
        pending_delivery.append(self._copy_event(event))

    def _deliver_events(self, events: list[AgentEvent]) -> None:
        if self._event_sink is None:
            return
        for event in events:
            try:
                self._event_sink(self._copy_event(event))
            except Exception as exc:  # noqa: BLE001 - observer failure is isolated.
                self._record_delivery_failure(event, exc)

    def _record_delivery_failure(self, event: AgentEvent, error: Exception) -> None:
        failure = make_event(
            AgentEventType.MAILBOX_EVENT_DELIVERY_FAILED,
            "Mailbox event sink delivery failed.",
            data={
                "failed_event_type": event.event_type.value,
                "error_type": type(error).__name__,
            },
        )
        with self._lock:
            self._events.append(failure)

    def _copy_event(self, event: AgentEvent) -> AgentEvent:
        return AgentEvent(
            event_type=event.event_type,
            message=event.message,
            step_index=event.step_index,
            data=dict(event.data),
            timestamp=event.timestamp,
        )
