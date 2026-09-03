# Week5 Team Runtime Failure Cases

## Evidence Boundary

These cases cover local Python/SQLite control-plane behavior. They do not prove
external side-effect exactly-once, process termination, distributed consensus or
safe concurrent patch integration. The B01 real Team smoke was run and failed;
weekend performance experiments remain NOT_RUN.

| ID | Injection | Required outcome |
| --- | --- | --- |
| F-W5-D7-01 | Invalid/cyclic Lead DAG | Reject before Worker dispatch |
| F-W5-D7-02 | Missing required capability | No claim; Team PAUSED with explicit reason |
| F-W5-D7-03 | GENERAL lacks one capability | No role fallback bypass |
| F-W5-D7-04 | Invalid weight | Equal-weight fallback and audit flag |
| F-W5-D7-05 | Node/global budget overrun | Fail closed; no further dispatch |
| F-W5-D7-06 | Retryable Worker timeout | New attempt only while Scheduler and Team budgets allow |
| F-W5-D7-07 | Terminal node failure | Descendants BLOCKED in same durable transaction |
| F-W5-D7-08 | Old runtime/generation/attempt result | Reject; current Task does not complete |
| F-W5-D7-09 | Artifact tamper/missing file | Hash/path validation failure |
| F-W5-D7-10 | Crash after result message, before ACK | Reconcile/replay claim and progress evidence |
| F-W5-D7-11 | Crash with unknown Worker usage | Conservatively exhaust node allocation; no free retry |
| F-W5-D7-12 | Concurrent writable nodes | Reject before Session/state creation |
| F-W5-D7-13 | Worker returns PAUSED | Preserve RUNNING evidence; new runtime reconciles attempt |
| F-W5-D7-14 | Team protocol error under eval | Structured failed actor result; no traceback contract |
| F-W5-D7-15 | SQLite/artifact persistence failure | Stop dispatch; never claim success |
| F-W5-D7-16 | Worker thread ignores cancel | Fence delayed result; do not claim process was stopped |
| F-W5-D7-17 | Worker reports forged diff/files/verification | Ignore claims; derive Git evidence at coordinator and leave verification to a trusted verifier/grader |
| F-W5-D7-18 | Exception/message/artifact contains credentials | Recursively redact at publication and artifact-write boundaries while retaining stable diagnostic codes |
| F-W5-D7-19 | Smoke exits after `STARTED` | Atomically publish terminal `COMPLETED`/`FAILED`; exception is recorded then re-raised |
| F-W5-D7-20 | `.git` metadata changes during Worker execution | Reject trusted workspace evidence and fail the common Coding result closed |
| F-W5-D7-21 | Binary, unreadable or escaping untracked path | Return empty trusted evidence with a structured failure; never use Worker claims as fallback |
| F-W5-D7-22 | Team child id contains `:` or path syntax | Generate a legal readable prefix plus raw-identity hash before entering Checkpoint/Patch Lane |
| F-W5-D7-23 | Native tool schema appears in message and provider tools | Keep one exact schema authority; compact catalog only in the system message |
| F-W5-D7-24 | Initial-context reads repeat across turns | Two all-cached turns stop as `CACHED_BATCH_STALL`; patch version permits fresh reads |
| F-W5-D7-25 | Redaction treats normal token source as a secret | Preserve source/domain language; use stricter fail-closed handling only for unknown exceptions |
| F-W5-D7-26 | Child `max_tool_calls` becomes generic Team failure | Normalize terminal node roots to Team budget/provider/environment/protocol categories |

## P0/P1 Risks

1. P0: shared-worktree concurrent writes remain disabled.
2. P0: final success must come from the unchanged external grader.
3. P0: stale three-layer fencing must never advance a current Task.
4. P1: progress/SQLite crash windows are conservative, not cross-store atomic.
5. P1: bounded threads are in-process execution, not Worker process isolation.
6. P1: a local artifact hash detects accidental/tampered bytes only while the
   reference itself remains trustworthy; this is not a signed evidence chain.

## Remaining Experiments

- Crash at every artifact/message/progress/Scheduler/ACK boundary.
- Disk full/fsync failure while writing Team progress or final artifact.
- Re-run B01 after the child-id/context/progress fixes. Both historical learner
  runs remain `RUN_FAILED`: run 1 reached patch but failed the Checkpoint id
  contract; run 2 exhausted child tools without a patch. No hidden-test leakage
  was found in the inspected artifacts.
- Weekend deterministic 1-vs-3 Worker benchmark and sequential/parallel ablation.
- Week6 per-Worker worktree, merge conflict and reviewer rejection cases.
