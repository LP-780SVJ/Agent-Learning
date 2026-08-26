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
