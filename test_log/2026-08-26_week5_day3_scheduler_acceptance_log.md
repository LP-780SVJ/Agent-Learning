# Week5 Day3 Task Scheduler Acceptance Log

## Evaluation Summary

- Date: 2026-08-26
- Module: Week5 Day3 Task Scheduler
- Capability layer: Multi-Agent Orchestration -> Task Scheduling / Dependency Management / Worker Lifecycle foundation
- Expected baseline short SHA: `3c23661`
- Observed HEAD: `3c23661985ddcdb39f78b7c4dc574b39620472df`
- Initial git status: clean
- Functional conclusion: **PARTIAL**
- Engineering evidence loop conclusion: **PARTIAL**
- Reason: core in-process Scheduler behavior passes tests and diagnostics for state machine, idempotent schedule, thread-level claim, ownership, retry, worker gates, and safe event fields. However, `event_sink` is invoked while holding a non-reentrant `Lock`, causing reentrant read deadlock and commit-after-callback-exception task loss. Benchmark evidence also has validity/reproducibility caveats.
- Non-claims: this acceptance does not prove distributed/cross-process claim, Worker crash recovery, heartbeat, durable queue/replay, Mailbox, Workspace Ownership, Worker execution, merge/review, or end-to-end Multi-Agent acceleration.

## Environment and Scope

- Python: `Python 3.11.16`
- pytest: `pytest 9.1.1`
- ruff: `ruff 0.16.2`
- Acceptance basis:
  - `learning-plan/week5/week5_plan.md`
  - `learning-plan/week5/day3.md`
  - `docs/design_decisions/DD-W5-03.md`
  - `docs/failure_cases/W5_SCHEDULER_FAILURE.md`
  - `docs/benchmark/W5_SCHEDULER.md`
  - `prompt/test_Agent.md`
- Production code audited:
  - `codeteam/agent_team/scheduler.py`
  - `codeteam/agent_team/dag.py`
  - `codeteam/agent_team/worker.py`
  - `codeteam/agent_team/__init__.py`
  - `codeteam/events.py`
- Tests/evals audited:
  - `tests/agent_team/test_scheduler.py`
  - `tests/agent_team/`
  - `evals/week5/benchmark_scheduler.py`

## Requirement -> Evidence Matrix

| Requirement | Evidence | Result |
|---|---|---|
| Reuse existing `TaskStatus`; no second `TaskState` | `TaskStatus` lives in `codeteam/agent_team/dag.py`; `scheduler.py` imports it. No separate scheduler enum found. | PASS |
| Status vocabulary includes PENDING, READY, CLAIMED, RUNNING, COMPLETED, FAILED, BLOCKED | Diagnostic printed all seven values; `dag.py` lines 10-17. | PASS |
| Transition table rejects invalid jumps | Diagnostic confirmed `PENDING->COMPLETED`, `READY->RUNNING`, `COMPLETED->RUNNING`, `FAILED->COMPLETED` are false. Tests partially cover this. | PASS_WITH_TEST_GAP |
| `TaskRuntimeRecord`, `TaskClaim`, `SchedulerResult` serializable | `tests/agent_team/test_scheduler.py` lines 94-112 pass JSON round-trip. | PASS |
| Runtime records are defensive snapshots | `runtime_records` uses `model_copy(deep=True)`; test mutates returned record and internal state remains unchanged. | PASS |
| `StaleTaskStateError` on expected status mismatch | `complete()` before `start()` raises and preserves CLAIMED/owner. | PASS |
| Illegal transition failure has no half write | Covered for stale complete; role mismatch/unavailable worker preserve queue/owner. Direct transition-table mutation can break operation but did not half-write in diagnostic. | PASS_WITH_RISK |
| Public `TASK_TRANSITIONS` cannot be externally corrupted | It is exported as a mutable dict. Diagnostic changed `TASK_TRANSITIONS[TaskStatus.PENDING] = ()`, making `schedule()` fail. | FAIL |
| Dependency-ready PENDING task becomes READY and queued | `schedule()` moves PENDING to READY and appends queue; tests pass. | PASS |
| Repeated `schedule()` idempotent | Test verifies second call schedules nothing and queue remains one item. | PASS |
| Queue and queued set consistent | Public queue evidence plus claim behavior pass; internal `_queued_node_ids` not directly asserted except through no duplicate/loss behavior. | PASS |
| Dependent blocked until prerequisite completed | `complete()` of A unlocks B; pre-completion B is not queued. | PASS |
| Failed terminal prerequisite blocks dependent | Non-retryable failure marks dependent BLOCKED and queue empty. | PASS |
| Complete auto-discovers dependent | `complete()` calls `_schedule_locked()`; test verifies B READY/queued. | PASS |
| Missing compatible role handling | `schedule()` fail-closed marks ready TEST task BLOCKED when registry has only BACKEND. | PASS_WITH_DESIGN_RISK |
| Registry can change after Scheduler creation | Diagnostic: missing-role task stayed BLOCKED after registering a TEST worker later. No clear fixed-registry contract found. | RISK |
| Unknown worker, role mismatch, BUSY/FAILED/STOPPED rejected | Tests cover all gates. | PASS |
| One Worker can hold one task | Claim marks worker runtime BUSY/current task; second claim raises `WorkerUnavailableError`. | PASS |
| Two workers claim one task atomically | Unit test and 50-run diagnostic: exactly one claim, no duplicate owner, no queue leftover. | PASS |
| Many workers claim many tasks without duplicate/loss | Unit test and 50-run diagnostic: 10 workers/10 tasks all claimed once. | PASS |
| Concurrency tests use Barrier/Event, not sleep | Tests use `Barrier`, no sleep. | PASS |
| Thread joins have timeout | Unit tests and benchmark use `thread.join()` without timeout. | FAIL_TEST_RELIABILITY |
| Claim linearization covers queue removal/status/owner/attempt/worker availability | `claim()` updates these under one lock before return; normal path passes. Callback exception breaks caller-visible atomicity. | PARTIAL |
| Role mismatch leaves task READY, owner None, still queued | Test covers this exact state. | PASS |
| Owner-only start/complete/fail | Tests cover non-owner complete/fail and state preservation. | PASS |
| start/complete/fail legal transitions | CLAIMED->RUNNING, RUNNING->COMPLETED/FAILED implemented and covered. | PASS |
| Retry under limit requeues and clears owner | Test covers max_attempts=2 retry to READY. | PASS |
| Retry exhausted/non-retryable terminal FAILED | Tests cover max_attempts=1 and non-retryable dependent block. | PASS |
| Attempt increments only on claim | Implementation increments in `claim()` only; retry test keeps attempt=1 after fail/requeue. | PASS |
| `failure_reason`, `claimed_at`, owner lifecycle | Complete/fail clear `claimed_at` and owner; retry preserves failure_reason. Main lifecycle covered. | PASS |
| Invalid `max_attempts` rejected | Diagnostic: max_attempts=0 raises `ValueError`. | PASS |
| Scheduler/DAG single state source | DD says `TaskRuntimeRecord.status` is source of truth and DAG topology source. Diagnostic confirms Scheduler ignores/does not update DAG status. Day3 tutorial also warns DAG and runtime status must not independently vary, so docs need a crisper snapshot contract. | PARTIAL |
| WorkerAgent copies `AgentInfo` and returns snapshots | Diagnostic: mutating original `AgentInfo` and public `worker.info` snapshot did not change registry identity/role. | PASS |
| `compatible(role)` is role match only | Worker registry code filters by role only; Scheduler keeps runtime availability separately. | PASS |
| Events use existing `AgentEvent` model and safe fields | `AgentEventType` contains scheduler events; test checks data field allowlist. | PASS |
| Event order matches state transitions | scheduled -> claimed -> started -> completed test passes. Failed/retried/blocked event order is partially inferred from code, not fully asserted. | PASS_WITH_TEST_GAP |
| Failed operations do not emit false success events | Role/stale/ownership tests preserve state; no direct event-negative assertions. | PASS_WITH_TEST_GAP |
| `event_sink` reentrant read safety | Diagnostic with `event_sink` reading `scheduler.events` left daemon schedule thread alive after 1s. | FAIL |
| `event_sink` exception isolation | Diagnostic raising on claimed event left task CLAIMED, worker BUSY, queue empty, and caller got `RuntimeError` instead of `TaskClaim`. | FAIL |
| Slow `event_sink` does not block scheduler | `event_sink` is called under `_lock`; slow callback blocks all scheduler methods. | FAIL |
| Benchmark fixed seed/warmup/30 measurements/sizes | Source uses seed `20260826`, 5 warmups, 30 measured runs, 100/500/1000 tasks, 1/4/8/16 workers. | PASS |
| Benchmark does not claim full task throughput/Multi-Agent speedup | Report says first-wave claim only and no end-to-end speedup. | PASS |
| Benchmark metric naming validity | `schedule_latency()` constructs DAG, Registry, and Scheduler before `schedule()`, so reported schedule latency includes setup cost. | PARTIAL |
| Benchmark reproducibility for current HEAD | Checked-in report was generated at commit `32c4666` with dirty tree, not observed clean HEAD. Reproduced to `/tmp` at current HEAD without overwriting repo. | PARTIAL |

## Commands, Exit Codes, Results, and Durations

| Command | Exit | Duration / Result |
|---|---:|---|
| `git rev-parse HEAD` | 0 | `3c23661985ddcdb39f78b7c4dc574b39620472df` |
| `git status --short` | 0 | clean |
| `.venv/bin/python --version` | 0 | `Python 3.11.16` |
| `.venv/bin/python -m pytest --version` | 0 | `pytest 9.1.1` |
| `.venv/bin/python -m ruff --version` | 0 | `ruff 0.16.2` |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile codeteam/agent_team/scheduler.py` | 0 | wall ~0.04s; no output |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m ruff check codeteam/agent_team tests/agent_team evals/week5/benchmark_scheduler.py` | 0 | `All checks passed!` |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/agent_team/test_scheduler.py -q` | 0 | `23 passed in 0.43s` |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/agent_team -q` | 0 | `102 passed in 0.45s` |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/task tests/planning tests/agent tests/session -q` | 0 | `202 passed in 19.96s` |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q` | 0 | `1303 passed, 6 skipped in 103.14s (0:01:43)` |
| Benchmark reproduction with `OUTPUT_PATH=/tmp/W5_SCHEDULER_acceptance_2026-08-26.md` | 0 | Completed all 12 task/worker cases; wrote only to `/tmp`; generated report says current HEAD `3c23661`, clean tree. |

## State Machine Audit

`TaskStatus.CLAIMED` is added to the existing DAG enum and Scheduler does not create a second state vocabulary. `TASK_TRANSITIONS` expresses the intended legal graph and runtime methods use `_transition_locked()` with expected status checks. Core invalid state behavior is correct in normal code paths. The main defect is that `TASK_TRANSITIONS` is mutable and publicly exported, so external code can alter Scheduler invariants.

## Queue and Schedule Audit

`schedule()` is idempotent for READY tasks, maintains a queue plus `_queued_node_ids`, blocks on terminal failed prerequisites, and fail-closes missing-role tasks. The missing-role path is irreversible: a task blocked before a compatible worker is registered remains BLOCKED after registry mutation. If Scheduler treats Registry as fixed team configuration, this needs explicit contract text; otherwise it is a design bug for dynamic team membership.

## Claim and Concurrency Audit

Normal claim paths are guarded by a single `Lock`, and claim updates queue membership, status, owner, attempt, and worker runtime availability in one critical section. Independent 50-run diagnostics showed no duplicate/lost claims for one-task contention and ten-task/ten-worker contention. However, tests and benchmark use `thread.join()` without timeout, so a regression could hang CI indefinitely.

## Ownership Audit

Owner-only lifecycle transitions are implemented and covered. Non-owner complete/fail fails without changing owner/status. `start()` requires CLAIMED, `complete()` and `fail()` require RUNNING, and worker availability is released on terminal/retry paths.

## Worker Audit

`WorkerAgent` defensively copies constructor input and public `info` output. `WorkerRegistry.compatible(role)` is role-only and deterministic by registration order; Scheduler maintains `_worker_runtime_status` and `_worker_current_task` independently, which matches the Day3 separation of role compatibility from runtime availability.

## Retry Audit

Attempts increment on successful claim. Retryable failure below `max_attempts` transitions FAILED -> READY, clears owner/claimed_at, preserves failure_reason, and requeues once. Exhausted or non-retryable failure stays terminal FAILED, and dependent tasks become BLOCKED on subsequent scheduling.

## Event Audit

Events use the existing `AgentEvent` and `AgentEventType` model. Data is limited to node_id, worker_id, from_status, to_status, attempt, and reason_code. No argv/env/secret/large payload exposure was found. Event emission is unsafe because `_record_event_locked()` appends and invokes `event_sink` while holding the scheduler lock.

## event_sink Diagnostics

1. Reentrant read:
   - Setup: `event_sink` calls `scheduler.events` during `schedule()`.
   - Safety harness: daemon thread plus `join(timeout=1.0)`.
   - Result: `event_sink_reentrant_thread_alive_after_1s= True`.
   - Conclusion: non-reentrant `Lock` plus callback inside lock deadlocks on public snapshot reads.

2. Callback exception on claimed:
   - Setup: `event_sink` raises `RuntimeError('sink boom')` on `scheduler.task_claimed`.
   - Result: caller received `RuntimeError`; `runtime_records['A']` was already `CLAIMED`, `owner_id='w1'`, `attempt=1`; queue was empty; second claim by same worker raised `WorkerUnavailableError`.
   - Conclusion: claim has been committed but caller did not receive `TaskClaim`, creating task-loss/half-commit risk.

3. Slow callback:
   - Code audit: callback is executed inside `_record_event_locked()` while the lock is held.
   - Conclusion: slow sinks block all scheduling operations.

## Scheduler/DAG Double State Source Audit

Diagnostics:

- After Scheduler `schedule/claim/start/complete`, Scheduler records were `{'A': 'completed', 'B': 'ready'}` while original DAG nodes stayed `{'A': 'pending', 'B': 'pending'}`.
- External `dag.replace_task_status('B', TaskStatus.COMPLETED)` after Scheduler construction changed DAG status but Scheduler record for B stayed `ready`.
- Constructing Scheduler from a DAG whose node A was already `COMPLETED` produced Scheduler record A as `pending`.

Interpretation:

- Implementation treats DAG as a topology snapshot and `TaskRuntimeRecord.status` as the runtime source of truth.
- `DD-W5-03` says this split is intentional, but `learning-plan/week5/day3.md` also says `TaskRuntimeRecord` and `TaskDAG.status` cannot independently vary. The observable behavior should be documented as "Scheduler snapshots DAG topology at construction and ignores DAG status thereafter", or code should enforce a single visible state path.

## Benchmark Validity Audit

- Source includes fixed seed, 5 warmups, 30 measured runs, task counts 100/500/1000, worker counts 1/4/8/16.
- Report correctly distinguishes first-wave claim throughput from full task throughput and explicitly rejects Multi-Agent speedup claims.
- Recovery latency, durable replay latency, and end-to-end success/cost/latency are `DEFERRED / NOT_RUN`.
- Validity issue: `schedule_latency()` includes DAG creation, WorkerRegistry creation, and Scheduler construction, so it is not pure schedule latency.
- Reproducibility issue: checked-in `docs/benchmark/W5_SCHEDULER.md` says it was generated at `32c4666` with dirty working tree. Acceptance reproduced the benchmark safely to `/tmp` on current HEAD `3c23661` and clean tree, but the committed report itself is stale relative to the acceptance baseline.

## Findings by Severity

### P1 - `event_sink` reentrant read deadlocks Scheduler

Evidence: `_record_event_locked()` invokes `self._event_sink(event)` while the non-reentrant lock is held. A sink that reads `scheduler.events` tries to acquire the same lock. Diagnostic thread remained alive after 1s. Recommendation: collect events inside the lock, release the lock, then call sinks; or use an event dispatcher that cannot call back into locked Scheduler state.

### P1 - `event_sink` exception creates committed claim without returned `TaskClaim`

Evidence: raising on `scheduler.task_claimed` propagated `RuntimeError` to caller after status became CLAIMED, owner became busy, attempt incremented, and queue entry was removed. Recommendation: either make event delivery best-effort and isolate sink exceptions, or emit callbacks after returning/with a transactional failure policy that rolls back state.

### P2 - Public mutable `TASK_TRANSITIONS` can break Scheduler invariants

Evidence: external mutation of `TASK_TRANSITIONS[TaskStatus.PENDING]` caused `schedule()` to fail. Recommendation: export an immutable mapping, e.g. `MappingProxyType` over immutable tuples, or hide the mutable implementation.

### P2 - Missing-role BLOCKED is permanent despite later Registry registration

Evidence: TEST task became BLOCKED with only BACKEND worker; registering TEST worker later and re-running `schedule()` did not unblock it. Recommendation: document Registry as immutable team configuration for a Scheduler instance, or add explicit unblock/replan semantics.

### P2 - Tests and benchmark concurrency joins lack timeout

Evidence: `tests/agent_team/test_scheduler.py` and `evals/week5/benchmark_scheduler.py` use `thread.join()` without timeout. Recommendation: add bounded joins and fail on live threads.

### P2 - Benchmark `schedule_latency` includes setup time

Evidence: `schedule_latency()` calls `build_scheduler()`, which builds DAG and Registry, then calls `schedule()`. Recommendation: rename metric or prebuild Scheduler inside each measured operation's setup phase and time only `schedule()`.

### P2 - Checked-in benchmark report is stale relative to acceptance HEAD

Evidence: repo report says commit `32c4666` and dirty tree; observed HEAD is `3c23661` and clean. Recommendation: regenerate report from clean accepted baseline if it is meant to be formal evidence.

### P3 - Transition tests do not enumerate all required forbidden transitions

Evidence: unit test checks PENDING->COMPLETED and COMPLETED->RUNNING, but not READY->RUNNING or FAILED->COMPLETED. Diagnostic verified all four. Recommendation: add explicit tests.

### P3 - Event-negative tests are incomplete

Evidence: tests validate normal event order and data allowlist, but do not assert failed role/ownership/stale operations emit no false success events. Recommendation: add event-negative tests.

## DD-W5-03 Evidence Conclusion

- Architecture decision "state-machine Scheduler instead of direct async fan-out": **PARTIALLY_SUPPORTED**.
- Supported by tests: in-process state machine, idempotent schedule, thread-level claim, owner-only lifecycle, retry cap, safe event fields.
- Not supported or unsafe: event sink execution model, immutable transition table, dynamic registry/unblock semantics, current benchmark metric naming, stale checked-in benchmark report.
- Correctly deferred: cross-process claim, crash/heartbeat recovery, durable queue/replay, Mailbox, Workspace Ownership, and end-to-end Multi-Agent success/cost/latency.

## Deferred Capabilities and Remaining Risks

- Cross-process/distributed atomic claim: DEFERRED / NOT_RUN.
- Worker crash, heartbeat, lost task recovery: DEFERRED / NOT_RUN.
- Durable queue and Session replay: DEFERRED / NOT_RUN.
- Mailbox and inter-worker coordination: DEFERRED / NOT_RUN.
- Workspace ownership and merge/review integration: DEFERRED / NOT_RUN.
- Worker execution and end-to-end Multi-Agent acceleration: INSUFFICIENT_EVIDENCE.
- Day4/Day5 recommendation: fix event sink transaction boundary before connecting durable event log, crash recovery, or external observers.

## Git Status Before / After

- Before acceptance: clean.
- After tests/diagnostics before log write: clean.
- Final status after log write: `?? test_log/2026-08-26_week5_day3_scheduler_acceptance_log.md`

## Modification Declaration

No production code, test code, tutorial, Design Decision, benchmark document, failure-case document, dependency file, or project configuration was modified. The only intended repository write is this allowed acceptance log:

`/Users/workplace/Agent-Learning/test_log/2026-08-26_week5_day3_scheduler_acceptance_log.md`
