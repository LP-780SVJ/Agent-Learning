# W5 Scheduler Failure Cases

## Scope

These cases cover Week5 Day3's in-process `TaskScheduler`. They do not cover
distributed locks, Worker crash recovery, heartbeat, durable queue replay, or
Mailbox coordination.

## F-W5-D3-01 Duplicate Claim

Reproducer:

```python
scheduler.schedule()
claim_a = scheduler.claim("worker-a")
claim_b = scheduler.claim("worker-b")
```

Expected evidence:

- Only one worker receives a `TaskClaim`.
- The task runtime record has exactly one `owner_id`.
- The ready queue no longer contains the claimed node.

Why it matters:

Duplicate claim causes two workers to edit, test, or report on the same unit of
work.

## F-W5-D3-02 Duplicate Enqueue

Reproducer:

```python
scheduler.schedule()
scheduler.schedule()
```

Expected evidence:

- The ready queue contains the node once.
- The second call reports the task as already ready instead of appending another
  copy.

Why it matters:

Duplicate queue entries can become duplicate claims later even if claim itself
uses a lock.

## F-W5-D3-03 Non-Owner Completion

Reproducer:

```python
claim = scheduler.claim("worker-a")
scheduler.start(claim.node_id, "worker-a")
scheduler.complete(claim.node_id, "worker-b")
```

Expected evidence:

- `TaskOwnershipError` is raised.
- The task remains `RUNNING`.
- The owner remains `worker-a`.

Why it matters:

Without owner checks, a worker can mark another worker's task complete or failed
without execution evidence.

## F-W5-D3-04 Worker Busy Claim

Reproducer:

```python
scheduler.schedule()
scheduler.claim("worker-a")
scheduler.claim("worker-a")
```

Expected evidence:

- The second claim raises `WorkerUnavailableError`.
- The first task ownership remains intact.

Why it matters:

The first Scheduler version assumes a worker can own one task at a time. Busy
workers claiming additional tasks breaks capacity accounting.

## F-W5-D3-05 Retry Loop

Reproducer:

```python
scheduler = TaskScheduler(dag, registry, max_attempts=1)
claim = scheduler.claim("worker-a")
scheduler.start(claim.node_id, "worker-a")
scheduler.fail(claim.node_id, "worker-a", "test failed")
```

Expected evidence:

- At max attempts, the task remains `FAILED`.
- It is not requeued.

Why it matters:

Unbounded retry is a cost and time failure mode for coding agents.

## F-W5-D3-06 Partial Ownership Write

Reproducer:

```python
scheduler.schedule()
scheduler.claim("wrong-role-worker")
```

Expected evidence:

- Claim fails with `WorkerRoleMismatchError`.
- The task remains `READY`.
- `owner_id` remains `None`.
- The task is still in the ready queue for a compatible worker.

Why it matters:

Failed claim must not leave half-written state such as owner set without status
change, or status claimed while the task remains queued.

## F-W5-D3-07 Event Sink Reentrant Deadlock

Reproducer:

```python
def sink(_event):
    scheduler.events

scheduler = TaskScheduler(dag, registry, event_sink=sink)
scheduler.schedule()
```

Expected evidence:

- `event_sink` is called after the Scheduler state lock is released.
- A sink can read `scheduler.events` or `scheduler.runtime_records` without
  deadlock.
- Tests run the call in a thread and use bounded `join(timeout=...)`.

Why it matters:

Observers often read Scheduler state for dashboards, logs, or durable stores. A
callback under a non-reentrant lock can freeze the runtime.

## F-W5-D3-08 Callback Exception After Committed Claim

Reproducer:

```python
def sink(_event):
    raise RuntimeError("sink failed")

claim = scheduler.claim("worker-a")
```

Expected evidence:

- The caller still receives `TaskClaim` after a committed claim.
- Status, owner, queue, attempt, and Worker availability remain consistent.
- A `scheduler.event_delivery_failed` event records the observer failure.
- The failure event is not recursively sent to the same failing sink.

Why it matters:

Event observers are not part of the domain transaction. Logging failure should
not lose a claimed task.

## F-W5-D3-09 Mutable Transition Table

Reproducer:

```python
TASK_TRANSITIONS[TaskStatus.READY] = (TaskStatus.RUNNING,)
```

Expected evidence:

- Mutation raises `TypeError`.
- Transition values are tuples and cannot be appended to.
- Scheduler still rejects forbidden paths such as `READY -> RUNNING` and
  `FAILED -> COMPLETED`.

Why it matters:

The transition table is a public contract. If external code can mutate it,
Scheduler invariants can change at runtime.

## F-W5-D3-10 Temporary Missing Role Incorrectly Terminal

Reproducer:

```python
scheduler = TaskScheduler(test_task_dag, backend_only_registry)
scheduler.schedule()
registry.register(test_worker)
scheduler.schedule()
```

Expected evidence:

- The first schedule reports `waiting_for_worker`, keeps the task `PENDING`,
  and does not enqueue it.
- The second schedule after registering a compatible Worker moves it to
  `READY`.
- `BLOCKED` is not used for temporary missing role.

Why it matters:

Team configuration can be assembled in stages. A temporary missing worker role
should not permanently kill a task.

## F-W5-D3-11 Unbounded Thread Join

Reproducer:

```python
thread.start()
thread.join()
```

Expected evidence:

- Tests and benchmark use `join(timeout=...)`.
- A live thread after timeout fails clearly.
- Barrier errors and thread exceptions are collected and asserted.

Why it matters:

Concurrency regressions should fail fast in CI, not hang forever.

## F-W5-D3-12 Unvalidated Cycle Enters Scheduler

Reproducer:

```python
dag = TaskDAG()
dag.add_task(task_a)
dag.add_task(task_b)
dag.add_dependency("a", "b")
dag.add_dependency("b", "a")

TaskScheduler(dag, registry)
```

Expected evidence:

- `TaskScheduler.__init__()` calls `TaskDAG.validate()` itself.
- The constructor raises `SchedulerInitializationError`.
- The raised error keeps `CycleDetectedError` as `__cause__`.
- Runtime records, queue, and event history are not partially initialized.

Why it matters:

If Scheduler trusts callers to validate first, an unvalidated cycle can produce
a no-ready-but-not-complete state where every task stays `PENDING` forever and
`schedule()` reports no scheduled, blocked, ready, or waiting task. Scheduler is
the runtime boundary, so it must be the final fail-fast validation gate.
