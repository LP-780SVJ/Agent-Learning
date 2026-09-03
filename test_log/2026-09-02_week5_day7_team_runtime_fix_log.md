# Week5 Day7 Team Runtime Coder Fix Log

- Date: 2026-09-02 (Asia/Shanghai)
- Branch: `week5`
- Baseline HEAD: `21a423e4276d7288e9f3198c11302b28ceeb779b`
- Scope: P0 credential redaction, P1 trusted workspace evidence, P2 smoke
  manifest terminalization, regression tests and evidence updates.
- Real provider/API calls: none.
- Benchmark/Ablation: NOT_RUN.
- Git actions: no reset, clean, stage, commit, merge, push or worktree creation.

## Baseline Reproduction

Protected acceptance command initially produced `7 passed, 3 failed`:

1. Team artifacts persisted an unredacted Worker exception marker.
2. Team common result copied forged Worker changed-files/diff/verification.
3. Failed real-smoke simulation left `real_llm_result=STARTED`.

The protected tester files, original acceptance log and existing B01 artifact
directory were not modified.

## Production Fixes

### P0: Shared Redaction Boundary

- Added one recursive `redact_sensitive_data()` implementation and reused it from
  Session persistence instead of maintaining a second regex set.
- Worker results are sanitized before publication. Unexpected exceptions retain a
  stable code/category, exception type, safe message and SHA-256 summary.
- Durable Scheduler failure reasons, Mailbox payloads and event payloads are
  sanitized before commit.
- Node/Team artifact writes sanitize again as defense in depth.
- Artifact JSON labels Worker result data as `worker_reported_*`; this remains
  diagnostic evidence, not trusted workspace/verification evidence.

### P1: Coordinator-Owned Workspace Evidence

- Worker changed-files, diff and verification are no longer copied into the common
  result.
- The coordinator obtains changed-files and tracked diff from `GitWorkspace`, then
  renders untracked UTF-8 regular files with the existing structured patch helper.
- Non-Git roots, subdirectory roots, path escape, symlink, binary/oversized or
  unreadable untracked data fail closed with empty trusted evidence and a
  structured failure.
- Security-relevant `.git` metadata (HEAD/config/packed-refs/refs) is fingerprinted
  before Worker execution and checked afterward. A mismatch rejects evidence.
- Trusted Team verification remains empty; external `AgentGrader` is still the
  visible/hidden correctness authority.
- DAG/control completion stays in `TeamRunArtifact.control_status`. A common Coding
  result with no real trusted workspace change is conservatively failed rather
  than expressing coding completion.

### P2: Terminal Smoke Manifest

- Dry run remains `NOT_RUN` with `network_call_performed=false`.
- A real attempt writes `STARTED`, then atomically replaces it with `COMPLETED` or
  `FAILED` and records run/task identity, terminal time, success, safe failure
  metadata and relative result references.
- Runner exceptions write a redacted `FAILED` manifest and are re-raised.
- Temp + flush + fsync + replace prevents partial JSON and keeps the prior valid
  state when replace fails.

## Added/Adjusted Regression Evidence

- Added `tests/agent_team/test_team_security_boundaries.py` for recursive
  redaction, stable error taxonomy, artifact/Mailbox/event sanitization, real
  tracked/untracked Git evidence, binary/symlink fail-closed behavior, `.git`
  metadata mutation and explicit Worker-claim artifact naming.
- Added `tests/scripts/test_day7_smoke_manifest.py` for success, failed result,
  runner exception, secret redaction and atomic replace failure.
- Updated Coder Team tests to create isolated temporary Git repositories and make
  real workspace changes instead of treating Worker self-reports as evidence.
- Mechanically fixed import order in `tests/evaluation/test_eval_command.py`.

## Verification Results

| Command | Result |
| --- | --- |
| Protected Day7 acceptance tests | PASS: 10 passed |
| Requested related Day7 regression set | PASS: 20 passed |
| New security + manifest regression set | PASS: 12 passed |
| `tests/agent_team tests/session tests/evaluation` | PASS: 604 passed |
| Requested Ruff scope | PASS: all checks passed |
| `mypy codeteam/agent_team tests/agent_team` | NON-ZERO: 37 historical diagnostics in 3 files; zero Day7 modified-file diagnostics |
| Full pytest | PASS: 1912 passed, 9 skipped |
| Sandbox suite | 62 passed, 9 skipped |

The 9 Sandbox skips all report permission denied for the Colima Docker socket.
Therefore real Docker integration boundaries were not verified in this run.

Mypy remains at the independent-acceptance baseline: 34 existing
`codeteam/llm/openai_compatible.py` `ModelTurn(**dict)` diagnostics and three old
intentional string/Enum invalid-input test diagnostics. Four temporary diagnostics
caused by the first artifact-field alias implementation were removed; no Day7
modified file appears in the final Mypy output.

## B01 Evidence Status

The existing learner-operated B01 run remains **RUN_FAILED** and was not rerun:

- two failed `apply_patch` calls and no effective patch;
- `workspace_version=0`, empty changed-files and final diff;
- visible/hidden acceptance failed;
- no-source-progress guard correctly paused without false success;
- no hidden-test leakage was found in the inspected B01 evidence;
- the old `STARTED` manifest is retained as historical evidence of the fixed
  manifest-state bug.

This one model failure is not presented as proof that the Team architecture is
invalid, and it is not presented as a passing smoke.

## Remaining Gates And Risks

- Independent tester re-acceptance is still required.
- The learner must rerun real B01 after that gate.
- Deterministic benchmark and sequential/parallel ablation remain NOT_RUN.
- Single-vs-Team remains DESIGNED / NOT_RUN.
- Team-owned trusted verification, signed evidence, per-Worker worktrees, patch
  integration and external side-effect exactly-once remain future work.
