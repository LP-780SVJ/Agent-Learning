# Week5 Day6 TaskStore Acceptance Correction

## Scope

- Date: 2026-09-01 (Asia/Shanghai)
- Branch: `week5`
- Starting HEAD: `c39f0fb025c92e7cb9d261b0444add299a7a94da`
- Benchmark/Ablation: `NOT_RUN / WEEKEND_PLANNED`
- Production code changed by this correction: none

The original acceptance log remains unchanged as historical evidence. This log
records an independent manager-level re-review after the coder fixed its P0/P1/P2
findings.

## Incorrect Acceptance Contract

The four remaining failures shared one parameterized test. Its prose required a
public facade mutation to be unavailable or durably committed, but its assertions
required both SQLite and live state to remain equal to the pre-call snapshot.
Those conditions reject the intended durable-commit behavior and contradict each
other for Scheduler claim, Registry heartbeat, Mailbox send and Lifecycle stop.

The test was corrected without changing production code or removing any facade
entry point. After each public mutation it now requires:

1. the SQLite snapshot equals `runtime.snapshot`;
2. durable revision advances exactly once;
3. post-call state differs from the pre-call snapshot; and
4. the affected live component equals the newly persisted state.

The test name and all four parameterized facade cases remain. The other twelve
acceptance cases and the original FAIL log were not altered.

## Independent Results

```text
Day6 acceptance:                         16 passed
Day6 focused + acceptance + hardening:  73 passed
Agent Team + Session:                  523 passed
Git + Execution:                       204 passed
Ruff touched scope:                    passed
Narrow Day6 mypy:                      passed, 8 files
Direct project-scope mypy:             module discovery fixed;
                                       71 historical/import-chain errors
Authorized Docker sandbox:             71 passed, 0 skipped
Authorized full pytest:              1874 passed, 0 failed, 0 skipped
git diff HEAD --check:                  passed
```

The direct mypy command now completes module discovery. Its 71 diagnostics are in
the previously classified 11 historical/import-chain files; no new Day6 production,
acceptance or hardening file has a diagnostic in the narrow audit.

## Conclusion

Day6 functional, durability, recovery, concurrency and selected security acceptance:
**PASS** for the documented local single-writer SQLite boundary. No production
defect remained behind the four corrected assertions.

Performance and ablation evidence remain `NOT_RUN`; this result does not prove
multi-primary or cross-machine recovery, arbitrary SIGKILL-point recovery, or
external side-effect exactly-once. The SQLite userspace `lstat -> open` TOCTOU
limitation also remains documented.
