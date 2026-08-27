from __future__ import annotations

from threading import Barrier, Thread
from threading import Event as ThreadEvent

import pytest
from pydantic import ValidationError

from codeteam.agent_team.mailbox import (
    AgentMailbox,
    AgentMessage,
    AgentMessageType,
    DuplicateAgentError,
    DuplicateMessageError,
    InvalidMessageError,
    MailboxError,
    MailboxFullError,
    UnknownAgentError,
)
from codeteam.agent_team.models import AgentIdentity
from codeteam.events import AgentEventType

JOIN_TIMEOUT_SECONDS = 2.0


def _identity(agent_id: str) -> AgentIdentity:
    return AgentIdentity(agent_id=agent_id, display_name=agent_id)


def _mailbox(
    *agent_ids: str,
    capacity_per_inbox: int = 1000,
    event_sink=None,
) -> AgentMailbox:
    mailbox = AgentMailbox(
        capacity_per_inbox=capacity_per_inbox,
        event_sink=event_sink,
    )
    for agent_id in agent_ids:
        mailbox.register_agent(_identity(agent_id))
    return mailbox


def _message(
    message_id: str = "msg-1",
    *,
    sender_id: str = "lead",
    recipient_id: str = "worker-1",
    message_type: AgentMessageType = AgentMessageType.INFO,
    payload: dict[str, object] | None = None,
    node_id: str | None = "node-1",
) -> AgentMessage:
    return AgentMessage(
        message_id=message_id,
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_type=message_type,
        task_id="task-1",
        node_id=node_id,
        correlation_id="corr-1",
        payload={} if payload is None else payload,
    )


def _join_threads(threads: list[Thread]) -> None:
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT_SECONDS)
    live_threads = [thread.name for thread in threads if thread.is_alive()]
    assert live_threads == []


def test_agent_message_json_round_trip() -> None:
    message = _message(
        message_type=AgentMessageType.TASK_COMPLETED,
        payload={"summary": "done"},
    )

    restored = AgentMessage.model_validate_json(message.model_dump_json())

    assert restored == message


@pytest.mark.parametrize(
    "field",
    ["message_id", "sender_id", "recipient_id", "task_id", "correlation_id"],
)
def test_agent_message_rejects_blank_required_fields(field: str) -> None:
    data = _message().model_dump()
    data[field] = " "

    with pytest.raises(ValidationError):
        AgentMessage.model_validate(data)


def test_agent_message_rejects_invalid_message_type() -> None:
    data = _message().model_dump()
    data["message_type"] = "not-a-message-type"

    with pytest.raises(ValidationError):
        AgentMessage.model_validate(data)


def test_agent_message_payload_default_is_independent() -> None:
    first = _message("msg-1", node_id=None)
    second = _message("msg-2", node_id=None)

    first.payload["key"] = "value"

    assert second.payload == {}
    assert first.node_id is None


def test_registers_lead_and_worker_addresses() -> None:
    mailbox = AgentMailbox()

    mailbox.register_agent(_identity("lead"))
    mailbox.register_agent(_identity("worker-1"))

    assert [identity.agent_id for identity in mailbox.registered_agents] == [
        "lead",
        "worker-1",
    ]


def test_register_agent_returns_defensive_snapshot() -> None:
    mailbox = AgentMailbox()
    identity = _identity("lead")

    registered = mailbox.register_agent(identity)
    identity.agent_id = "mutated"
    registered.agent_id = "also-mutated"

    assert [item.agent_id for item in mailbox.registered_agents] == ["lead"]


def test_duplicate_agent_is_rejected_without_overwrite() -> None:
    mailbox = AgentMailbox()
    mailbox.register_agent(_identity("lead"))

    with pytest.raises(DuplicateAgentError):
        mailbox.register_agent(AgentIdentity(agent_id="lead", display_name="new"))

    assert mailbox.registered_agents[0].display_name == "lead"


def test_unknown_sender_recipient_and_receiver_are_rejected() -> None:
    mailbox = _mailbox("lead", "worker-1")

    with pytest.raises(UnknownAgentError, match="missing"):
        mailbox.send(_message(sender_id="missing"))
    with pytest.raises(UnknownAgentError, match="missing"):
        mailbox.send(_message(recipient_id="missing"))
    with pytest.raises(UnknownAgentError, match="missing"):
        mailbox.receive("missing")

    assert mailbox.queue_size("worker-1") == 0


def test_send_and_receive_point_to_point_message() -> None:
    mailbox = _mailbox("lead", "worker-1", "worker-2")
    sent = mailbox.send(
        _message(
            message_type=AgentMessageType.TASK_ASSIGNED,
            payload={"goal": "implement"},
        )
    )

    received = mailbox.receive("worker-1")

    assert sent.message_id == "msg-1"
    assert received == sent
    assert mailbox.receive("worker-1") is None
    assert mailbox.receive("worker-2") is None


def test_receive_empty_inbox_returns_none() -> None:
    mailbox = _mailbox("lead")

    assert mailbox.receive("lead") is None


def test_receive_preserves_per_inbox_fifo_order() -> None:
    mailbox = _mailbox("lead", "worker-1")
    for index in range(3):
        mailbox.send(_message(f"msg-{index}", payload={"index": index}))

    received = [mailbox.receive("worker-1") for _ in range(3)]

    assert [message.message_id for message in received if message] == [
        "msg-0",
        "msg-1",
        "msg-2",
    ]


def test_duplicate_message_id_is_rejected_even_after_receive() -> None:
    mailbox = _mailbox("lead", "worker-1")
    mailbox.send(_message("msg-1"))
    assert mailbox.receive("worker-1") is not None

    with pytest.raises(DuplicateMessageError):
        mailbox.send(_message("msg-1"))

    assert mailbox.queue_size("worker-1") == 0


def test_send_defensively_copies_payload() -> None:
    mailbox = _mailbox("lead", "worker-1")
    payload: dict[str, object] = {"nested": {"status": "before"}}
    original = _message("msg-1", payload=payload)

    sent = mailbox.send(original)
    original.payload["nested"] = {"status": "mutated"}
    sent.payload["nested"] = {"status": "also-mutated"}

    received = mailbox.receive("worker-1")
    assert received is not None
    assert received.payload == {"nested": {"status": "before"}}

    received.payload["nested"] = {"status": "receiver-mutated"}
    assert mailbox.receive("worker-1") is None


def test_capacity_full_fails_closed_and_receive_releases_capacity() -> None:
    mailbox = _mailbox("lead", "worker-1", capacity_per_inbox=1)
    mailbox.send(_message("msg-1"))

    with pytest.raises(MailboxFullError):
        mailbox.send(_message("msg-2"))

    assert mailbox.queue_size("worker-1") == 1
    assert mailbox.receive("worker-1") is not None
    mailbox.send(_message("msg-2"))
    assert mailbox.queue_size("worker-1") == 1


def test_broadcast_sends_independent_messages_with_shared_correlation_id() -> None:
    mailbox = _mailbox("lead", "worker-a", "worker-b", "worker-c")

    sent = mailbox.broadcast(
        sender_id="lead",
        recipient_ids=("worker-a", "worker-b", "worker-c"),
        message_type=AgentMessageType.SHUTDOWN_REQUESTED,
        task_id="task-1",
        node_id="node-1",
        payload={"reason": "stop"},
        correlation_id="corr-broadcast",
    )

    assert len({message.message_id for message in sent}) == 3
    assert {message.correlation_id for message in sent} == {"corr-broadcast"}
    assert [message.recipient_id for message in sent] == [
        "worker-a",
        "worker-b",
        "worker-c",
    ]
    assert mailbox.receive("worker-a") == sent[0]
    assert mailbox.receive("worker-b") == sent[1]
    assert mailbox.receive("worker-c") == sent[2]


def test_broadcast_rejects_empty_or_duplicate_recipients() -> None:
    mailbox = _mailbox("lead", "worker-a")

    with pytest.raises(InvalidMessageError):
        mailbox.broadcast(
            sender_id="lead",
            recipient_ids=(),
            message_type=AgentMessageType.INFO,
            task_id="task-1",
        )
    with pytest.raises(InvalidMessageError):
        mailbox.broadcast(
            sender_id="lead",
            recipient_ids=("worker-a", "worker-a"),
            message_type=AgentMessageType.INFO,
            task_id="task-1",
        )

    assert mailbox.queue_size("worker-a") == 0


def test_broadcast_unknown_recipient_is_all_or_nothing() -> None:
    mailbox = _mailbox("lead", "worker-a", "worker-b")

    with pytest.raises(UnknownAgentError):
        mailbox.broadcast(
            sender_id="lead",
            recipient_ids=("worker-a", "missing", "worker-b"),
            message_type=AgentMessageType.INFO,
            task_id="task-1",
        )

    assert mailbox.queue_size("worker-a") == 0
    assert mailbox.queue_size("worker-b") == 0


def test_broadcast_capacity_failure_is_all_or_nothing() -> None:
    mailbox = _mailbox("lead", "worker-a", "worker-b", capacity_per_inbox=1)
    mailbox.send(_message("existing", recipient_id="worker-b"))

    with pytest.raises(MailboxFullError):
        mailbox.broadcast(
            sender_id="lead",
            recipient_ids=("worker-a", "worker-b"),
            message_type=AgentMessageType.INFO,
            task_id="task-1",
        )

    assert mailbox.queue_size("worker-a") == 0
    assert mailbox.queue_size("worker-b") == 1


def test_concurrent_producers_do_not_drop_or_duplicate_messages() -> None:
    producer_count = 8
    messages_per_producer = 25
    mailbox = _mailbox(
        *(["recipient"] + [f"sender-{index}" for index in range(producer_count)])
    )
    barrier = Barrier(producer_count)
    errors: list[BaseException] = []

    def producer(index: int) -> None:
        try:
            barrier.wait()
            for message_index in range(messages_per_producer):
                mailbox.send(
                    _message(
                        f"msg-{index}-{message_index}",
                        sender_id=f"sender-{index}",
                        recipient_id="recipient",
                        payload={"producer": index, "index": message_index},
                    )
                )
        except (RuntimeError, MailboxFullError, UnknownAgentError) as exc:
            errors.append(exc)

    threads = [
        Thread(target=producer, args=(index,), name=f"producer-{index}")
        for index in range(producer_count)
    ]
    for thread in threads:
        thread.start()
    _join_threads(threads)

    assert errors == []
    received: list[AgentMessage] = []
    while True:
        message = mailbox.receive("recipient")
        if message is None:
            break
        received.append(message)

    assert len(received) == producer_count * messages_per_producer
    assert len({message.message_id for message in received}) == len(received)


def test_audit_events_use_safe_metadata_without_payload() -> None:
    mailbox = _mailbox("lead", "worker-1")
    mailbox.send(_message(payload={"secret": "do-not-log"}))
    assert mailbox.receive("worker-1") is not None

    allowed_keys = {
        "message_id",
        "sender_id",
        "recipient_id",
        "message_type",
        "task_id",
        "node_id",
        "queue_size",
        "reason_code",
        "correlation_id",
        "recipient_count",
        "failed_event_type",
        "error_type",
    }
    event_types = [event.event_type for event in mailbox.events]

    assert AgentEventType.MAILBOX_MESSAGE_SENT in event_types
    assert AgentEventType.MAILBOX_MESSAGE_RECEIVED in event_types
    for event in mailbox.events:
        assert set(event.data) <= allowed_keys
        assert "payload" not in event.data
        assert "secret" not in event.data


def test_event_sink_can_read_mailbox_state_without_deadlock() -> None:
    mailbox_ref: dict[str, AgentMailbox] = {}
    seen: list[tuple[int, int]] = []

    def sink(_event: object) -> None:
        mailbox = mailbox_ref["mailbox"]
        seen.append((len(mailbox.events), mailbox.queue_size("worker-1")))

    mailbox = AgentMailbox(event_sink=sink)
    mailbox_ref["mailbox"] = mailbox
    mailbox.register_agent(_identity("worker-1"))
    mailbox.register_agent(_identity("lead"))
    seen.clear()
    thread = Thread(target=lambda: mailbox.send(_message()))

    thread.start()
    _join_threads([thread])

    assert seen[-1] == (3, 1)


def test_slow_event_sink_does_not_hold_mailbox_lock() -> None:
    entered_sink = ThreadEvent()
    release_sink = ThreadEvent()

    def sink(_event: object) -> None:
        entered_sink.set()
        release_sink.wait(timeout=JOIN_TIMEOUT_SECONDS)

    mailbox = _mailbox("lead", "worker-1", event_sink=sink)
    send_thread = Thread(target=lambda: mailbox.send(_message()))
    sizes: list[int] = []

    def read_state() -> None:
        sizes.append(mailbox.queue_size("worker-1"))

    send_thread.start()
    assert entered_sink.wait(timeout=JOIN_TIMEOUT_SECONDS)
    reader_thread = Thread(target=read_state)
    reader_thread.start()
    _join_threads([reader_thread])
    release_sink.set()
    _join_threads([send_thread])

    assert sizes == [1]


def test_raising_event_sink_does_not_rollback_send_or_receive() -> None:
    delivered_types: list[AgentEventType] = []

    def sink(event: object) -> None:
        delivered_types.append(event.event_type)  # type: ignore[attr-defined]
        raise RuntimeError("sink failed")

    mailbox = _mailbox("lead", "worker-1", event_sink=sink)

    sent = mailbox.send(_message())
    received = mailbox.receive("worker-1")

    assert received == sent
    assert mailbox.queue_size("worker-1") == 0
    assert delivered_types[-2:] == [
        AgentEventType.MAILBOX_MESSAGE_SENT,
        AgentEventType.MAILBOX_MESSAGE_RECEIVED,
    ]
    assert AgentEventType.MAILBOX_EVENT_DELIVERY_FAILED in [
        event.event_type for event in mailbox.events
    ]


def test_events_property_returns_defensive_copies() -> None:
    mailbox = _mailbox("lead", "worker-1")
    mailbox.send(_message())

    event = mailbox.events[-1]
    event.data["message_id"] = "mutated"

    assert mailbox.events[-1].data["message_id"] == "msg-1"


def test_failed_send_does_not_emit_false_success_event() -> None:
    mailbox = _mailbox("lead", "worker-1")

    with pytest.raises(UnknownAgentError):
        mailbox.send(_message(recipient_id="missing"))

    assert AgentEventType.MAILBOX_MESSAGE_SENT not in [
        event.event_type for event in mailbox.events
    ]


def test_public_api_exports_mailbox_objects() -> None:
    from codeteam.agent_team import AgentMailbox as ExportedAgentMailbox
    from codeteam.agent_team import AgentMessage as ExportedAgentMessage
    from codeteam.agent_team import AgentMessageType as ExportedAgentMessageType
    from codeteam.agent_team import DuplicateAgentError as ExportedDuplicateAgentError
    from codeteam.agent_team import (
        DuplicateMessageError as ExportedDuplicateMessageError,
    )
    from codeteam.agent_team import InvalidMessageError as ExportedInvalidMessageError
    from codeteam.agent_team import MailboxError as ExportedMailboxError
    from codeteam.agent_team import MailboxFullError as ExportedMailboxFullError
    from codeteam.agent_team import UnknownAgentError as ExportedUnknownAgentError

    assert ExportedAgentMailbox is AgentMailbox
    assert ExportedAgentMessage is AgentMessage
    assert ExportedAgentMessageType is AgentMessageType
    assert ExportedDuplicateAgentError is DuplicateAgentError
    assert ExportedDuplicateMessageError is DuplicateMessageError
    assert ExportedInvalidMessageError is InvalidMessageError
    assert ExportedMailboxError is MailboxError
    assert ExportedMailboxFullError is MailboxFullError
    assert ExportedUnknownAgentError is UnknownAgentError
