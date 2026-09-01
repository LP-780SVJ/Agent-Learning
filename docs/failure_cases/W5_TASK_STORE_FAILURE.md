# W5 TaskStore and Session Resume Failure Cases

## Evidence Boundary

Day6 covers local, single-host process persistence with normalized SQLite and
Session writer ownership. Tests include selected real subprocess `os._exit`
failures. They do not prove distributed consensus, arbitrary crash-point recovery
or external side-effect exactly-once. Benchmark/Ablation: NOT_RUN.

## Case Matrix

| ID | Failure injection | Required invariant / evidence |
| --- | --- | --- |
| F-W5-D6-01 | Stale `expected_revision` | No Team state/event change; `TeamStateConflictError` |
| F-W5-D6-02 | Exception after state rows are written but before commit | Old revision and events remain readable |
| F-W5-D6-03 | `os._exit` inside SQLite transaction | Reopened DB is intact; no state/event split brain |
| F-W5-D6-04 | Unsupported schema or corrupt DB | Explicit typed error; never initialize an empty replacement |
| F-W5-D6-05 | Old WorkerLease/TaskClaim after resume | New runtime epoch rejects both without mutating new state |
| F-W5-D6-06 | Old IN_FLIGHT Mailbox claim | Reconciliation releases to PENDING, preserves delivery attempt and dedupe |
| F-W5-D6-07 | CLAIMED/RUNNING with retry available | Owner cleared, Task READY once, attempt preserved |
| F-W5-D6-08 | CLAIMED/RUNNING with exhausted retry | Task FAILED; descendants BLOCKED; no queue entry |
| F-W5-D6-09 | In-flight Task plus unknown Git mutation | Session becomes RECOVERY_REQUIRED; no blind replay |
| F-W5-D6-10 | Team DB ahead of Session revision hint | Next resume reconciles gap, creates new runtime, publishes new hint |
| F-W5-D6-11 | Team DB behind Session hint | Fail closed and release writer lock |
| F-W5-D6-12 | Two processes resume same Session | Only one writer/runtime publishes RUNNING |
| F-W5-D6-13 | Missing runtime builder or Team DB | RECOVERY_REQUIRED event/state; no empty-runtime fallback |
| F-W5-D6-14 | UTC restart cooldown across process | Preserve wall deadline; derive fresh monotonic delay at hydration |
| F-W5-D6-15 | Public raw component mutation | Public facade routes through one durable mutation gate; nested references never return raw components |
| F-W5-D6-16 | DB/WAL/SHM path is a symlink | Reject before SQLite open; external target bytes remain unchanged |
| F-W5-D6-17 | Event seq/session/revision drift | `load` and `load_events` reject the complete history as corrupted |
| F-W5-D6-18 | Cyclic DAG, mismatched Worker identity or non-finite claim time | Reject at the formal model boundary before DB creation |
| F-W5-D6-19 | Pure no-op capture changes only time projection | No Store commit; audit-only event still advances revision |

## P0/P1 Risks

1. **P0: blind replay after unknown Git effects.** Never change RUNNING directly
   to active execution when side effects cannot be reconciled.
2. **P0: stale epoch authorization.** Old runtime_id/lease/claim/message claim must
   not mutate the new runtime.
3. **P0: state/event split brain.** Team state and event must share one SQLite
   transaction; event sinks are observers only.
4. **P1: cross-store revision inversion.** SQLite ahead is a known crash window;
   SQLite behind Session is not automatically trusted.
5. **P1: Mailbox loss/duplication.** Never pop from memory before a durable claim;
   ACK must match message, runtime, claim id and delivery attempt.
6. **P1: stale cooldown clock.** Never persist monotonic timestamps across process
   boundaries; preserve an aware UTC deadline and rebuild monotonic time.
7. **P1: path/permission leakage.** Team DB must stay under a real protected Session
   directory, including WAL sidecars.
8. **P1: poisoned live runtime.** A persistence failure after a live mutation must
   halt later mutations until reconstructed from durable state.
9. **P0: public durability bypass.** A durable runtime must expose controlled
   facades, including lifecycle restart/sweep; raw Day5 components remain usable
   only when deliberately constructed as standalone in-memory services.
10. **P1: userspace path-check race.** `lstat` blocks ordinary DB/sidecar symlinks,
    but cannot eliminate replacement between check and SQLite open.

## Independent Acceptance Contract Conflict

The acceptance task requires direct facade mutations to produce a durable commit.
Four unchanged test instances instead assert that both SQLite and live state equal
the pre-call snapshot after Scheduler claim, Registry heartbeat, Mailbox send and
Lifecycle stop. A real acknowledged mutation cannot satisfy both properties.
The production fix follows the stated durability contract and a separate regression
suite proves live state equals the newly committed snapshot. The original four
cases remain evidence requiring tester/manager clarification; no no-op facade or
snapshot-equality workaround was introduced.

## Remaining Failure Experiments

- Kill after Git command succeeds but before checkpoint/effect evidence is durable.
- Disk full, fsync failure and WAL checkpoint interruption on supported platforms.
- Large event/message histories and retention pressure.
- Schema migration from a real prior Team schema (V1 currently refuses unknown).
- Real external Worker processes and command idempotency keys.

## Reproduction

```bash
.venv/bin/python -m pytest tests/agent_team/test_sqlite_team_state_store.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_store_process_crash.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_reconciliation.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_hydration.py -q
.venv/bin/python -m pytest tests/session/test_team_runtime_resume.py -q
.venv/bin/python -m pytest tests/session/test_team_double_resume.py -q
.venv/bin/python -m pytest tests/session/test_team_resume_process_crash.py -q
```

## Future Failure Record Template

```text
ID / severity / status:
HEAD / dirty state / OS / Python / SQLite:
Session state_version / Team revision / runtime_id:
Task attempt / Worker generation / message claim:
Git/checkpoint facts before injection:
Exact crash point and subprocess return code:
Expected durable state/event relationship:
Actual Session/SQLite/Git state:
Root cause / fix / regression:
What remains unverified:
```
