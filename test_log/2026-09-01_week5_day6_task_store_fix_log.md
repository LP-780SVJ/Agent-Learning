# Week5 Day6 TaskStore Acceptance Fix Log

## Scope

- Branch: `week5`
- Starting HEAD: `c39f0fb025c92e7cb9d261b0444add299a7a94da`
- Date: 2026-09-01 (Asia/Shanghai)
- Existing dirty and untracked Day6 work was preserved.
- No stage, commit, merge, push, reset, API, Benchmark or Ablation was run.
- Benchmark/Ablation: `NOT_RUN / WEEKEND_PLANNED`.

This is coder self-verification after independent acceptance. It does not replace
an independent tester rerun.

## Production Fixes

1. `DurableTeamRuntime` now owns private raw Registry, Scheduler, Mailbox,
   Lifecycle, Coordinator and Store references. Public controlled facades preserve
   reads and route mutation back through the durable gate. Nested component
   references return facades, not raw mutable services.
2. Durable lifecycle coverage now includes `restart_worker()` and `sweep()`.
   State, generation/restart reservation, task recovery and emitted events are
   captured in one Store commit before success returns.
3. Pure no-op operations no longer advance revision, event cursor or `updated_at`.
   Volatile UTC projections of monotonic restart deadlines are excluded from the
   business-state comparison. Audit-only events still commit.
4. `TeamStateSnapshot` rejects cyclic DAGs with bounded Kahn traversal, Worker map
   key/identity mismatch and nested Task records with non-finite/negative
   `claimed_at` before Store initialization.
5. Scheduler durable export retains every Worker ownership key, including stopped
   or unowned Workers.
6. SQLite checks DB, WAL, SHM and journal paths with `lstat` before opening them;
   symlinks raise `TeamStatePathError`. External targets remain unchanged. A
   userspace check/open TOCTOU window remains and is not described as kernel path
   confinement.
7. Store load validates the complete event/meta chain: session id, contiguous seq,
   positive/nonfuture revision, nondecreasing revision and `last_event_seq`.
8. `tests/__init__.py` gives mypy one canonical tests package. Direct and explicit
   package-base commands now discover modules consistently.

## Regression Tests

Added `tests/agent_team/test_day6_hardening_regressions.py` with 13 tests covering:

- public facade durable commits and nested raw-reference closure;
- no-op versus audit-only revision behavior;
- restart success, factory failure and sweep persistence;
- DB/WAL/SHM symlink rejection without target mutation;
- event sequence, session, future revision and revision-regression corruption.

Focused new regression result: `13 passed`.

## Independent Acceptance Mapping

The original acceptance command improved from `2 passed, 14 failed` to
`12 passed, 4 failed`.

Fixed instances:

- durable `restart_worker` and `sweep`: 2;
- no-op schedule revision: 1;
- cyclic DAG: 1;
- Worker key/identity mismatch: 1;
- NaN/+Inf/-Inf `claimed_at`: 3;
- event/meta revision drift: 1;
- database symlink target protection: 1.

Remaining four instances are the parameterized direct-component case for
Scheduler, Registry, Mailbox and Lifecycle. The task specification requires these
facade calls to produce a durable commit. The unchanged test instead asserts that
SQLite and live state both equal the pre-call snapshot. An acknowledged mutation
cannot both commit and leave state/revision unchanged. Production follows the
stated durability contract; the new facade regression verifies that live state
equals the newly committed snapshot. No no-op facade, hidden bypass, AttributeError,
or model-equality workaround was introduced.

## Verification

```text
.venv/bin/python -m pytest tests/agent_team/test_day6_task_store_acceptance.py -q
12 passed, 4 failed

.venv/bin/python -m pytest <eight original Day6 focused files> -q
44 passed

.venv/bin/python -m pytest tests/agent_team tests/session -q
519 passed, 4 failed

.venv/bin/python -m pytest tests/git tests/execution -q
204 passed

.venv/bin/python -m ruff check codeteam/agent_team codeteam/session tests/agent_team tests/session
All checks passed!

.venv/bin/python -m mypy codeteam/agent_team codeteam/session tests/agent_team tests/session
71 errors in 11 files; duplicate-module discovery fixed; no Day6 fix-file diagnostics

.venv/bin/python -m mypy --explicit-package-bases codeteam/agent_team codeteam/session tests/agent_team tests/session
71 errors in the same 11 historical/import-chain files

.venv/bin/python -m pytest -q
1861 passed, 4 failed, 9 skipped

.venv/bin/python -m pytest tests/sandbox -q -rs
sandboxed run: 62 passed, 9 skipped (Colima socket permission)
authorized host rerun: 71 passed

git diff HEAD --check
passed with no output
```

The 71 mypy diagnostics are the previously recorded PyYAML stub, parser, tools,
failure, search, sandbox, LLM, orchestrator and three old enum-construction test
diagnostics. The former duplicate-module discovery failure is gone. No new Day6
diagnostic remains.

## Conclusion

Coder hardening implementation: functionally verified except for the four mutually
incompatible acceptance assertions described above.

Independent re-acceptance: `BLOCKED_BY_ACCEPTANCE_CONTRACT_CLARIFICATION`.

Day6 must not be reported as independently accepted until the tester/manager
clarifies whether direct facade mutations should commit (the written requirement)
or be no-ops (the current four assertions).
