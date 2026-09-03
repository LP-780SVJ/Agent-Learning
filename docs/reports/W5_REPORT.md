# Week5 Team Runtime Report

## Current Conclusion

Week5 Day1-Day7 local control-plane implementation is present. Independent Day7
acceptance found P0/P1/P2 trust-boundary defects, and two real B01 runs exposed
child-ID and context/progress defects. Production fixes and deterministic
regressions are present; post-fix real smoke and independent re-acceptance remain
pending. Benchmark and Ablation remain NOT_RUN.

## Day7 Delivered Scope

- TeamCodingRuntime implements the common CodingRuntime protocol.
- WorkerExecutor reuses CodingAgentRuntime with bounded child requests.
- Static three-Worker capability matching and GENERAL fallback are enforced.
- Lead weight allocation is constrained by one global ledger and 20% reserve.
- Node and Team artifacts are atomic, relative-path constrained and hash referenced.
- Result publication uses durable Mailbox claim/ACK and three-layer fencing.
- Day6 SQLite reconciliation can feed `resume_team`; usage replays from durable
  progress evidence and unknown crash usage fails closed.
- AgentEvalRunner keeps the same grader and emits Team protocol failures as
  structured results.
- Worker workspace/verification fields are explicitly untrusted. Coordinator-owned
  Git evidence is the only source for common changed-files/diff; trusted Team
  verification is intentionally empty until a trusted verifier or AgentGrader runs.
- Shared recursive redaction protects Worker errors, nested result data, Mailbox,
  durable events and artifacts. Artifact persistence sanitizes a second time.
- Smoke manifests now transition atomically from STARTED to COMPLETED/FAILED and
  include terminal time, success, run/task identity, safe failure metadata and
  relative result references.

## Evidence Status

| Evidence | Status |
| --- | --- |
| Scripted deterministic tests | CODER_PASS |
| Process `os._exit` boundary | CODER_PASS (selected point) |
| Full regression | POST_FIX_PASS: 1918 passed, 9 Docker-permission skips |
| Docker boundary | POST_FIX_PASS: 71 passed after authorized Colima access |
| B01 real LLM Team smoke | 2 historical RUN_FAILED; deterministic causes fixed; post-fix rerun pending |
| Deterministic benchmark | NOT_RUN: correctness gate remains closed pending re-acceptance |
| Sequential/parallel ablation | NOT_RUN: correctness gate remains closed |
| Single/Team architecture comparison | DESIGNED / NOT_RUN |

## B01 Observed Facts

- Run 1 issued two reasonable `apply_patch` calls; both were rejected because the
  Team child task id contained colons that Checkpoint correctly forbids.
- Run 2 made no patch and exhausted the 32-call child cap after first-request
  compaction and repeated initial-context reads.
- Both runs ended with `workspace_version=0`, empty changed-files/diff and failed
  visible/hidden acceptance. No layer falsely reported coding success.
- No hidden-test leakage was found in the inspected B01 messages/artifacts.
- The original stale `STARTED` manifest, illegal child id, duplicated native tool
  schemas, permanent initial-context cache exemption and coarse Team failure
  category now have production fixes and regressions.

These failed samples are not evidence that the Team architecture is categorically
ineffective. They exposed deterministic wiring defects. An offline B01 regression
now completes the production Team/Single/Patch/Checkpoint/verification/diff chain,
but the real Provider gate is still unmet until the learner reruns it.

## Week6 Gate

Do not enable real multi-Worker concurrent coding until per-Worker worktree
ownership, patch artifact integration, deterministic merge order, conflict policy
and reviewer/verification gates have tests. A successful B01 one-Worker smoke only
proves adapter wiring.

## Type/Lint Boundary

Day7 touched-scope Ruff passes. Direct Team mypy still exits non-zero due to 34
historical OpenAI adapter diagnostics and three intentional old invalid-input test
calls; the final output contains no Day7 file. These are not reported as a passing
repository-wide type gate.
