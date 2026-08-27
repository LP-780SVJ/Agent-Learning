# W5 Mailbox Failure Cases

## Scope

These cases cover Week5 Day4's in-process `AgentMailbox`. They do not cover
heartbeat, worker crash recovery, ack/nack, durable replay, SQLite mailbox,
exactly-once delivery, cross-process producers, or distributed ordering.

## F-W5-D4-01 Unknown Sender or Recipient

Reproducer:

```python
mailbox.send(
    AgentMessage(
        message_id="msg-1",
        sender_id="missing",
        recipient_id="worker-1",
        message_type=AgentMessageType.INFO,
        task_id="task-1",
        correlation_id="corr-1",
    )
)
```

Expected evidence:

- `UnknownAgentError` is raised for unknown sender or recipient.
- No recipient inbox is modified.
- No false `mailbox.message_sent` event is recorded.

Why it matters:

Message routing must fail closed when addresses are not registered. Otherwise a
typo can silently drop coordination data.

## F-W5-D4-02 Duplicate Message ID

Reproducer:

```python
mailbox.send(message_with_id_msg_1)
mailbox.receive("worker-1")
mailbox.send(message_with_id_msg_1)
```

Expected evidence:

- The second send raises `DuplicateMessageError`.
- The duplicate is rejected even after the first message was received.
- The inbox is not modified by the duplicate.

Why it matters:

Retries and repeated tool calls can produce the same message again. Duplicate
message IDs need a stable fail-closed behavior before Day6 durable replay.

## F-W5-D4-03 Mailbox Overflow

Reproducer:

```python
mailbox = AgentMailbox(capacity_per_inbox=1)
mailbox.send(msg_1)
mailbox.send(msg_2)
```

Expected evidence:

- The second send raises `MailboxFullError`.
- The first message remains queued.
- No message is silently dropped.
- Receiving one message releases capacity for a later send.

Why it matters:

Coding agents can emit large progress payloads or stall while consuming. An
unbounded inbox can become a memory failure mode.

## F-W5-D4-04 Partial Broadcast

Reproducer:

```python
mailbox.broadcast(
    sender_id="lead",
    recipient_ids=("worker-a", "missing", "worker-b"),
    message_type=AgentMessageType.INFO,
    task_id="task-1",
)
```

Expected evidence:

- The operation raises `UnknownAgentError` or `MailboxFullError`.
- No recipient receives any new broadcast message.
- Broadcast prechecks happen before append.

Why it matters:

Partial broadcast splits team state: some agents react to an instruction while
others never see it.

Regression evidence:

- `evals/week5/ablation_mailbox.py` compares the full all-or-nothing broadcast
  with a one-off looped `send()` ablation.
- In the deterministic failure workloads, full broadcast produces zero partial
  deliveries, while the looped-send ablation leaves earlier recipients with
  messages when a later recipient is full or unknown.

## F-W5-D4-04B Broadcast Batch Duplicate Generated ID

Reproducer:

```python
# Force uuid.uuid4() to return the same UUID for every recipient, then:
mailbox.broadcast(
    sender_id="lead",
    recipient_ids=("worker-a", "worker-b", "worker-c"),
    message_type=AgentMessageType.INFO,
    task_id="task-1",
)
```

Expected evidence:

- `DuplicateMessageError` is raised before any inbox append.
- No recipient receives a new message.
- No broadcast success event is recorded.
- The duplicate ID does not enter `_seen_message_ids`; a later public `send()`
  using that ID can still succeed.

Why it matters:

Batch-level duplicate IDs split observability and dedupe semantics even when
all recipients are valid. The Mailbox must fail closed instead of attempting an
unbounded regeneration loop.

## F-W5-D4-05 Payload Mutation Leak

Reproducer:

```python
payload = {"nested": {"status": "before"}}
message = AgentMessage(..., payload=payload)
mailbox.send(message)
message.payload["nested"] = {"status": "mutated"}
received = mailbox.receive("worker-1")
received.payload["nested"] = {"status": "mutated-again"}
```

Expected evidence:

- The queued message keeps the original payload.
- Mutating the returned `AgentMessage` does not mutate internal state.
- Audit events never contain full payload.

Why it matters:

External references should not corrupt communication history or leak secrets
into observability data.

## F-W5-D4-06 Event Sink Reentrant Deadlock

Reproducer:

```python
def sink(_event):
    mailbox.events
    mailbox.queue_size("worker-1")

mailbox = AgentMailbox(event_sink=sink)
mailbox.send(message)
```

Expected evidence:

- `event_sink` is called after the Mailbox lock is released.
- A sink can read Mailbox state without deadlock.
- Tests use bounded thread joins.

Why it matters:

Dashboards and persistence adapters commonly read state while observing events.
Calling observers while holding a non-reentrant lock can freeze the runtime.

## F-W5-D4-07 Event Sink Exception

Reproducer:

```python
def sink(_event):
    raise RuntimeError("sink failed")

sent = mailbox.send(message)
received = mailbox.receive("worker-1")
```

Expected evidence:

- `send()` and `receive()` still return their committed results.
- Queue state remains consistent.
- `mailbox.event_delivery_failed` is recorded.
- Delivery failure events are not recursively sent to the failing sink.

Why it matters:

External observers are not part of the mailbox transaction. Logging failure
must not lose messages or hide successful communication.

## F-W5-D4-08 Worker Crash After Destructive Receive

Reproducer:

```python
message = mailbox.receive("worker-1")
# process crashes before message is handled
```

Expected evidence:

- Day4 marks this as a known limitation.
- The in-memory Mailbox cannot restore the message.
- Recovery is deferred to Day5 heartbeat and Day6 durable store design.

Why it matters:

Destructive receive is simple and fast, but it is not a recovery protocol.

## F-W5-D4-09 Multi-Producer Ordering Misread

Reproducer:

```python
# two threads send to the same recipient at nearly the same time
```

Expected evidence:

- Every accepted message is received exactly once within the process.
- Per-inbox FIFO follows successful append linearization order.
- No claim is made about producer wall-clock ordering.

Why it matters:

Overclaiming global ordering can produce tests that pass locally but fail under
real thread scheduling.

## F-W5-D4-10 Cumulative Memory Retention

Reproducer:

```python
mailbox = AgentMailbox(capacity_per_inbox=1)
for index in range(1_000_000):
    mailbox.send(unique_message(index))
    mailbox.receive("worker-1")
```

Expected evidence:

- `capacity_per_inbox` limits only the current queued backlog per inbox.
- `_seen_message_ids` continues to grow with every accepted unique message.
- `_events` continues to grow with registration, send, receive, broadcast, and
  delivery failure events.

Why it matters:

Day4 uses global lifetime message ID dedupe to reject replayed IDs after
destructive receive. That is a correctness tradeoff, not a global memory bound.
The first implementation should be scoped to a team, task, or session lifecycle
and released after that lifecycle completes.

Remaining risk:

Long-lived mailboxes with very high message volume can grow from retained seen
IDs and event history even when all inboxes are empty. Dedupe windows, event
archival, durable replay, and recovery policy are deferred to Day6.
