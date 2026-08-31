# Week5 Day5 Lifecycle: Coder Implementation Verification

## Scope and Authority

Date: 2026-08-31. Branch: `week5`. Base HEAD:
`25dc4c70ac433e0924a65cd2f3a43a320a812b63`.
This is Coder first-round implementation verification, not independent tester
acceptance. User authorized implementing the tutorial's ten steps and explicitly
deferred Benchmark/Ablation to the weekend.

At start, only `learning-plan/week5/day5.md` was staged plus modified (`AM`).
Its index blob remains `39669324b43e3156589531ae2512e3016f25a755`; this task did
not edit the tutorial or stage/commit anything. No fixture or main-repo Git
mutation was used in Day5 tests.

## Implementation Map

| Tutorial step | Implementation / direct evidence |
| --- | --- |
| 1. Contracts | contracts.py; strict WorkerLease/TaskClaim fields, policy validation, owned attempt summaries |
| 2. Registry and transactions | registry.py + coordination.py; sole dynamic Worker authority; WorkerRegistry alias; shared draft/rollback lock |
| 3. Mandatory fencing | scheduler.py + test_fencing.py; same worker and same generation late attempt1 cannot start/complete/fail attempt2 |
| 4. Clock and heartbeat | injectable monotonic Clock; same-reading revision updates; invalid/backward clocks rejected; bootstrap grace |
| 5. Timeout scan | immutable candidates; exact >= deadline; scan has no business-state/audit-success mutations |
| 6. Recovery | CLAIMED/RUNNING loss plus idle Worker; attempt budget; stale candidates; no FAILED-to-READY Worker release |
| 7. Restart | outside-lock factory, bounded reservations/cooldown, identity preservation, generation publish, late ticket rejection |
| 8. Lifecycle orchestration | synchronous sweep/stop; no successor selection or Worker execution |
| 9. Audit and migration | scalar transaction/generation/attempt metadata; observer isolation; exports; explicit-claim caller migration |
| 10. Evidence | deterministic/concurrent tests, DD, failure cases and NOT_RUN experiment plan |

New production files: `codeteam/agent_team/contracts.py`, `coordination.py`,
`registry.py`, `lifecycle.py`. Updated `models.py`, `scheduler.py`, `worker.py`,
`__init__.py` and `codeteam/events.py`.

New tests: `tests/agent_team/test_registry.py`, `test_fencing.py`, `test_lifecycle.py`.
Migrated existing Scheduler/Mailbox tests to explicit leases and saved claims,
retaining prior ownership/role/retry/event assertions. New test cases: 100.

`evals/week5/benchmark_scheduler.py` only migrated its two initial claim calls to
the mandatory lease API; it was NOT executed. Existing historical Scheduler
benchmark data now carries a stale-after-migration notice.

## Baseline

| Command | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest tests/agent_team -q` | 165 passed in 4.19s |
| `.venv/bin/python -m ruff check codeteam/agent_team codeteam/events.py tests/agent_team` | Exit 0 |
| `.venv/bin/python -m mypy codeteam/agent_team tests/agent_team` | Exit 1; 5 pre-existing diagnostics in 4 files |

## Post-implementation Verification

All commands below were actually run using the project interpreter.

| Command | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest tests/agent_team/test_worker.py tests/agent_team/test_registry.py -q` | 32 passed in 0.05s |
| `.venv/bin/python -m pytest tests/agent_team/test_scheduler.py -q` | 40 passed in 0.07s |
| `.venv/bin/python -m pytest tests/agent_team/test_lifecycle.py -q` | 70 passed in 0.09s |
| `.venv/bin/python -m pytest tests/agent_team/test_mailbox.py -q` | 46 passed in 4.08s |
| `.venv/bin/python -m pytest tests/agent_team/test_registry.py tests/agent_team/test_fencing.py tests/agent_team/test_lifecycle.py -q` | 100 passed in 0.10s |
| `.venv/bin/python -m pytest tests/agent_team -q` | 265 passed in 4.29s |
| `.venv/bin/python -m pytest tests/agent tests/session tests/execution -q` | 363 passed in 28.81s |
| `.venv/bin/python -m ruff check codeteam/agent_team codeteam/events.py tests/agent_team evals/week5/benchmark_scheduler.py` | Exit 0, all checks passed |
| `.venv/bin/python -m mypy codeteam/agent_team tests/agent_team` | Exit 1; 4 pre-existing diagnostics in 3 untouched files, 21 source files checked |
| `.venv/bin/python -m pytest -q` (normal Codex sandbox) | 1674 passed, 9 skipped in 54.60s |
| `.venv/bin/python -m pytest tests/sandbox -q -rs` (normal Codex sandbox) | 62 passed, 9 skipped in 0.67s |
| `.venv/bin/python -m pytest tests/sandbox -q -rs` (authorized Docker access) | 71 passed in 3.28s; zero skips |
| `.venv/bin/python -m pytest -q` (authorized Docker access, final full run) | 1683 passed in 58.47s; zero failures, zero skips |
| `git diff --check` | Exit 0 |

The nine normal-sandbox skips all report permission denied accessing Docker at
`unix:///Users/sqlee/.colima/default/docker.sock`. They were NOT counted as real
container-boundary passes. The subsequent authorized Sandbox run actually passed
all 71 tests. Day5's new tests do not require Docker or any provider API.
The final authorized full regression also passed all 1683 tests in one run.

## Type-check Classification

Remaining diagnostics match the pre-change baseline and are not new lifecycle
errors; the overall mypy command is nevertheless NOT passing:

- `codeteam/agent_team/dag.py:197`: missing annotation for `dependents`.
- `tests/agent_team/test_models.py:107`: string supplied to typed AgentRole argument.
- `tests/agent_team/test_models.py:110`: string supplied to typed AgentStatus argument.
- `tests/agent_team/test_dag.py:86`: string supplied to typed TaskStatus argument.

The existing unannotated `received` list in the touched Scheduler test was annotated
as `list[AgentEvent]`. A transient new-test duplicate-module import diagnostic was
fixed with relative package imports, not ignored. No Any/skip/xfail was added to
hide production or type-check errors. No unrelated DAG/model test rewrite was made.

## Design and Failure Evidence

See `docs/design_decisions/DD-W5-05.md`,
`docs/failure_cases/W5_LIFECYCLE_FAILURE.md` and
`docs/benchmark/W5_LIFECYCLE.md`.

Tests use FakeClock, Barrier/Event and bounded joins. They inspect task/worker/queue
snapshots, callback counts and audit ordering, not just successful method returns.
Failure injections prove draft rollback, stale result rejection and bounded
logical recovery. They do not prove killing an actual process or external effects
being exactly-once.

## Remaining Work / Conclusion

Day5 implementation and first-round functional/concurrency verification pass;
independent tester acceptance remains pending. The package mypy gate retains the
four baseline diagnostics listed above. Benchmark/Ablation are PLANNED / NOT_RUN.

Not implemented: WorkerExecutor, real process lifecycle/preemptible factory,
progress timeout, SQLite/cross-process Team resume, Team-token enforcement inside
Runtime/SafeExecution, and bounded event archival. Existing single-agent Runtime,
Session and SafeExecution were not modified or replaced.
