# Week5 Day6 TaskStore + Session Integration Implementation Log

## Scope and Evidence Boundary

Implemented the Day6 local process-persistence design on branch `week5` from
starting HEAD `c39f0fb025c92e7cb9d261b0444add299a7a94da`. The user selected immediate
Task/Message table normalization, durable Mailbox claim/ack, aware UTC restart
deadlines and publication order `Team commit -> hydrate -> Session RUNNING`.

No Git stage/commit/merge/push/worktree operation was performed. Benchmark and
Ablation remain WEEKEND_PLANNED / NOT_RUN. No real API was called.

This is Coder self-verification, not independent tester acceptance. It proves
selected local SQLite and subprocess crash boundaries, not distributed recovery,
external side-effect exactly-once or arbitrary SIGKILL-point recovery.

## Implemented Contract

- Added schema-versioned `TeamStateSnapshot`, durable Worker/Message/Event models
  and typed persistence errors.
- Added normalized `SQLiteTeamStateStore` tables for DAG, Task runtime, Worker,
  queue/waiting/ownership, Mailbox, dedupe and Team events.
- State and event use one SQLite transaction with revision CAS; DB/WAL sidecars
  remain in the protected Session directory.
- Added Registry/Scheduler/Mailbox package-owned export/hydration boundaries.
- Added durable Mailbox `claim -> ack/release`; no pop-before-persist delivery.
- Added `TeamStateReconciler` for new runtime epoch, retry/terminal closure,
  generation advancement, STOPPED preservation and old message-claim release.
- Preserved restart cooldown as aware UTC deadline and rebuilt monotonic deadline.
- Added `DurableTeamRuntime` mutation/persistence gateway and poison-on-unproven-
  persistence behavior.
- Added Session schema v6 `TeamStateRef` and named runtime-builder integration.
- Resume order is Team CAS commit, hydrate fresh objects, then Session RUNNING
  save/event. Team-ahead gap reconciles; Team-behind-Session fails closed.

## Test Evidence

Focused new Day6 suite:

```text
.venv/bin/python -m pytest \
  tests/agent_team/test_team_state_models.py \
  tests/agent_team/test_sqlite_team_state_store.py \
  tests/agent_team/test_team_reconciliation.py \
  tests/agent_team/test_team_hydration.py \
  tests/agent_team/test_team_store_process_crash.py \
  tests/session/test_team_runtime_resume.py \
  tests/session/test_team_double_resume.py \
  tests/session/test_team_resume_process_crash.py -q

44 passed in 1.61s
```

Day5 lifecycle plus Session regression:

```text
.venv/bin/python -m pytest tests/agent_team tests/session -q
494 passed in 8.56s
```

Touched-scope Ruff:

```text
.venv/bin/python -m ruff check \
  codeteam/agent_team codeteam/session tests/agent_team tests/session
All checks passed!
```

Full regression:

```text
.venv/bin/python -m pytest -q
1836 passed, 9 skipped in 61.33s
```

Sandbox capability audit:

```text
.venv/bin/python -m pytest tests/sandbox -q -rs
62 passed, 9 skipped in 0.83s
```

All nine skips are existing Docker integration tests. The Docker CLI/daemon could
not connect to `/Users/sqlee/.colima/default/docker.sock` because permission was
denied. No Day6 persistence/process test was skipped. This run is not evidence
that the real Docker boundary passed in this environment.

`git diff --check` passed with no output.

## Type Audit

The repository's direct target command:

```text
.venv/bin/python -m mypy codeteam/agent_team codeteam/session \
  tests/agent_team tests/session
```

is blocked before checking by the existing namespace-package mapping of
`tests/agent_team/team_state_helpers.py` as both `agent_team.*` and
`tests.agent_team.*`.

Re-running the same scope with `--explicit-package-bases` completed type discovery
and reported 71 existing diagnostics in 11 files. They are in the historical
PyYAML stub/import chain, parser/tools/search/LLM/orchestrator modules and three
pre-existing enum-construction tests. Earlier Day5 `dag.py` inference diagnostics
were corrected where touched. No diagnostic remains in the new Day6 production
or test files. No `Any`, ignore or dependency/config change was introduced to hide
the historical gate.

## Crash and Concurrency Evidence

- Real child process exits with `os._exit(91)` after SQLite state writes but
  before transaction commit; reopened old revision/events remain intact.
- Real child process commits Team revision and exits before Session save; next
  resume reconciles the DB-ahead window and publishes a new revision.
- Real child process mutates a temporary Git worktree and exits; RUNNING Task
  resume becomes `RECOVERY_REQUIRED` instead of blind retry.
- Two real Python processes race to resume one Session; only the writer-lock owner
  reaches RUNNING, and pause releases ownership.
- Tests use `tmp_path`, argv subprocesses, `shell=False`, timeouts and output
  capture; no main repository or fixture repository is mutated.

## Remaining Work

- Independent tester acceptance.
- Weekend 100/500/1000 Task Benchmark/Ablation with raw samples and manifest.
- Explicit future Team schema migration (V1 rejects unsupported versions).
- Disk-full/fsync/WAL checkpoint fault injection.
- Real Worker processes and external side-effect idempotency/exactly-once design.
- Cross-machine/multi-primary runtime remains out of scope.

## Conclusion

Day6 functional implementation and Coder verification: PASS.

Independent acceptance and weekend Benchmark/Ablation: PENDING / NOT_RUN.
