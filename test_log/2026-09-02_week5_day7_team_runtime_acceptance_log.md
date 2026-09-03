# Week5 Day7 TeamCodingRuntime Independent Acceptance Log

- Date: 2026-09-02 (Asia/Shanghai)
- Repository: `/Users/root/workspace/Agent-Learning`
- Branch: `week5` (`ahead 1` of `origin/week5`)
- Baseline HEAD: `21a423e4276d7288e9f3198c11302b28ceeb779b`
- Baseline state: dirty; Day7 production code, tests, documentation, eval scripts,
  and B01 evidence were staged/unstaged/untracked inputs under acceptance.
- Git actions: no worktree, branch, stage, commit, merge, push, reset, clean, or
  Git configuration change.
- Real provider/API calls in this acceptance: none.

## Capability Mapping

Day7 spans the following capability layers:

| Capability | What this acceptance must prove |
|---|---|
| Multi-Agent Orchestration | Lead plan, DAG, role/capability matching, bounded dispatch, retry and blocked propagation compose into one Team run. |
| Durable Runtime | Day6 `DurableTeamRuntime` remains the durable control-plane gateway and can be hydrated/resumed. |
| Concurrency Control | Coordinator is the only durable writer; claims are unique; active work is bounded; stale results cannot commit. |
| Budget Accounting | Parent hard budgets are allocated once, reserve is explicit, failed/unknown attempts are charged, and aggregate usage is auditable. |
| Evaluation Integration | Team implements the existing `CodingRuntime` boundary and remains subject to the same `AgentEvalRunner` and `AgentGrader`. |
| Observability | Team/node artifacts, events, usage, timing, failure taxonomy, manifests, and raw experiment evidence remain inspectable. |

The intended architecture is present: `WorkerExecutor` invokes an injected
`CodingRuntime`; it does not contain a second Agent loop. `TeamCodingRuntime`
coordinates Day5/Day6 Scheduler, Registry, Mailbox, lifecycle, and SQLite state.
DAG terminal state is not treated as external code correctness; the grader remains
the final authority.

## Baseline And Integrity

Representative initial SHA256 fingerprints:

| Input | SHA256 |
|---|---|
| `learning-plan/week5/day7.md` | `bcddbed6f71d2f86ef672d7bd0962d84f66df16d1e55b9245bb6a9587e5c5140` |
| `codeteam/agent_team/team_runtime.py` | `07abf3009652ab20ad76a0d2baf39a02eb4b7a05b65c5cd01b22986e9fd8c903` |
| `codeteam/agent_team/worker_executor.py` | `e387a1bd8352fc883f3e12b19b62f3c8e25e07b95b15c0e7e8c5b1bb4eb3c18c` |
| `codeteam/agent_team/team_artifacts.py` | `0298539fb60b3475bf5528b1c73ec7d64e47bf758ebc3e6a8a12f21e869593e4` |
| `codeteam/agent_team/team_budget.py` | `aa63f97ad40e731e805c8901346881ba2c52711c12cb0a8d5f9e81914d7dee01` |
| `codeteam/agent_team/worker_pool.py` | `c688d21270c4446009aad105c0b281ad5f1325c9d36582a016e0f67f1389dc79` |
| `codeteam/evaluation/agent_runner.py` | `c82821b36f35bfded831cf1b5e0b4a5bab6d8858d517b82f9c173af4720e0e94` |
| `evals/week5/benchmark_team_runtime.py` | `3bb82e73d36c94ec3eb2afa38ef909e7b7f4c5e31b5000a6992d15cec0c39265` |
| `evals/week5/compare_single_team.py` | `cdd7b4f6aff248e0e38753c148d926ef9c164cebb726ead56af8e7070e976b3b` |
| `evals/week5/smoke_team_runtime.py` | `a1ee5082be6151e5e37c256ccfc19156fafc14008266632ae274642d8b1ed215` |
| B01 `results.jsonl` | `8c437881e7c993bcc4c58ef6288110c3f20cdc49c8b51bc5b0f34a256e380abd` |
| B01 `team_smoke_manifest.json` | `228cc3267d187a817cca6c7d0d0b3605a9c73006415e5e3ef9910018cf8cc3b6` |

The complete frozen set contained 111 files. End-of-run rehash reported
`files=111 exact_match=true`. Therefore the tester did not modify production code,
learning content, docs, eval scripts, existing test inputs, or B01 evidence.

## Files Added

- `tests/agent_team/test_day7_team_runtime_acceptance.py`
  - 7 test functions / 9 parameterized cases.
  - Covers request mapping, provider/model and verification preservation, budget
    caps/reserve, all three fence dimensions, atomic artifact replace failure,
    missing/truncated/symlink artifact attacks, Worker evidence provenance, and
    credential redaction.
- `tests/scripts/test_day7_smoke_manifest_acceptance.py`
  - Uses a fully fake runner and fake provider construction boundary; performs no
    network/API call.
  - Reproduces the missing final smoke-manifest transition.
- This log.

No existing file was modified by the tester.

## Requirement Coverage

| Requirement | Implementation / test evidence | Result |
|---|---|---|
| Worker assignment/claim maps to `CodingAgentRunRequest` | `WorkerExecutor.build_runtime_request`; existing `test_worker_executor.py`; new contract/fence test | PASS |
| Provider/model, visible verification, budgets and fencing are retained | New `test_worker_executor_preserves_runtime_contract_budget_and_fence` | PASS |
| WorkerExecutor only invokes injected CodingRuntime | Source inspection plus capturing runtime test | PASS |
| Runtime COMPLETED/FAILED/PAUSED/exception are structured | Existing Team runtime/recovery tests and B01 PAUSED artifact | PASS |
| Three static Workers and exact-role priority | `static_worker_infos`; `test_team_budget_and_pool.py` | PASS |
| GENERAL fallback requires capability subset | Existing pool and runtime tests | PASS |
| No compatible Worker returns structured PAUSED | `test_no_compatible_worker...` and stopped-worker case | PASS |
| Shared writable worktree is rejected | `test_concurrent_writable_shared_workspace_fails_before_state_creation` | PASS |
| Lead weight range and observable equal-weight fallback | Pydantic normalization plus budget tests | PASS |
| 20% Team reserve and no aggregate step/tool inflation | Existing and new budget allocation assertions | PASS |
| Retry and unknown-crash usage are charged | Retry test and process-crash recovery test | PASS |
| Steps/tool calls/repairs are hard gates | Ledger tests and child request validation | PASS |
| Tokens/cost without configured caps are statistics only | New ledger audit test; optional caps remain explicit policy | PASS |
| Linear/diamond/fan-out/layered definitions exist | Deterministic benchmark workload plans; underlying DAG/Scheduler suites | PARTIAL: benchmark blocked, so all shapes were not measured in this run |
| 1/3 Worker control result and real overlap | Existing Barrier-based three-worker test; focused suite passed | PASS for tested fan-out; PARTIAL across all benchmark shapes |
| Bounded concurrency and no busy polling | Bounded `ThreadPoolExecutor`; `wait(FIRST_COMPLETED)`; Barrier evidence | PASS |
| Coordinator is sole durable writer | Worker thread returns value only; controller performs all durable operations | PASS by source and existing control-plane tests |
| Retry exhaustion, BLOCKED propagation, unrelated branches | Scheduler/DAG suites included in 592-test combined run | PASS at control-plane layer |
| runtime_id/generation/attempt fencing | Existing generation test plus three new parameterized fence cases | PASS |
| Result order artifact -> claim -> durable transition -> ack | Source inspection and Day6 durable mailbox tests | PARTIAL: no new Team-level injected commit-before-ack test |
| Commit failure does not ack; duplicate delivery idempotent | Day6 persistence/mailbox tests | PARTIAL at Day7 integration boundary |
| Crash/resume uses new runtime and charges unknown usage | `test_team_runtime_recovery.py` process test | PASS |
| Writer conflict/CAS/persistence fail closed | Day6 hardening and task-store acceptance suites | PASS at durable gateway; PARTIAL for Team final artifact publication |
| Team/node artifacts atomic and relative | Existing artifact tests plus injected replace and symlink tests | PASS |
| Absolute/`..`/symlink escape rejected | `RuntimeArtifactRef` validation and new symlink escape test | PASS |
| Hash mismatch, missing, truncated artifact detected | Existing hash test plus new missing/truncated tests | PASS |
| Artifacts do not leak credentials | New deterministic redaction test | **FAIL** |
| changed_files/diff/verification are not trusted Worker claims | New empty-workspace forged-evidence test | **FAIL** |
| Team satisfies CodingRuntime and uses same EvalRunner/Grader | Public `run`; evaluation integration tests; runner source | PASS |
| Hidden checks occur after runtime stops | `AgentEvalRunner`: runtime invocation precedes `grader.grade` | PASS |
| Hidden output never enters Worker messages/artifacts | B01 field/marker audit found no hidden-path/test-content indicator | PASS for inspected B01; no claim beyond inspected evidence |
| DAG terminal cannot force final success | Same external grader and B01 `success=false` despite completed orchestration stages | PASS |
| Explicit `max_tool_calls` is not replaced by `max_steps*3` | `test_agent_eval_runner.py` explicit value assertion | PASS |
| PAUSED/failure taxonomy is structured | B01 maps Worker PAUSED/no-progress to Team PAUSED/interrupted and Eval failed | PASS, with coarse Team category noted |

## Command Results

Commands were executed in the requested order unless explicitly marked as a
supplemental diagnostic:

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest tests/agent_team/test_worker_executor.py -q` | PASS: 1 passed, 0 failed/skipped/error |
| `.venv/bin/python -m pytest tests/agent_team/test_team_runtime.py -q` | PASS: 8 passed |
| `.venv/bin/python -m pytest tests/agent_team/test_team_runtime_recovery.py -q` | PASS: 2 passed |
| `.venv/bin/python -m pytest tests/evaluation/test_team_runtime_integration.py -q` | PASS: 2 passed |
| `.venv/bin/python -m pytest tests/agent_team tests/session tests/evaluation -q` | FAIL: 592 passed, 2 failed, 0 skipped/error |
| `.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team tests/evaluation tests/scripts` | FAIL: 1 existing import-order diagnostic in `tests/evaluation/test_eval_command.py` |
| `.venv/bin/python -m mypy codeteam/agent_team tests/agent_team` | FAIL: 37 errors in 3 files; classification below |
| `.venv/bin/python -m pytest -q` | FAIL: 1895 passed, 3 failed, 9 skipped, 0 errors |
| `.venv/bin/python -m pytest tests/sandbox -q -rs` | Initial restricted run: 62 passed, 9 skipped due Colima socket permission |
| Same Sandbox command via normal escalation | PASS: 71 passed, 0 skipped/failed/error |
| `git diff --check` | PASS |
| Supplemental focused new tests | 7 passed, 3 stable product/script failures |
| Supplemental Ruff on the two new test files | PASS |
| `.venv/bin/python evals/week5/compare_single_team.py --output /tmp/week5-day7-acceptance-20260902/single-team-plan` | PASS; plan generated and validated |

### Mypy Classification

Formal command: 37 errors in 3 files.

- Day7 new/modified production files: **0 reported errors**.
- Tester-added tests: **0 reported errors**.
- Existing import-chain debt: 34 `arg-type` diagnostics in
  `codeteam/llm/openai_compatible.py` around `ModelTurn(**dict)` construction.
- Existing older test debt: 3 enum/string `arg-type` diagnostics in
  `tests/agent_team/test_models.py` and `tests/agent_team/test_dag.py`.

A supplemental Mypy run targeting only the two new tests produced no diagnostic
in either new test, but expanded their imports and surfaced 58 existing diagnostics
across six production files. These include one missing `PyYAML` stub and existing
typing errors in instructions, tree-sitter parsing, file tools, ripgrep search,
sandbox environment inspection, and the OpenAI-compatible adapter. This does not
clear the repository's static gate, but it distinguishes the tester changes from
pre-existing import-chain debt.

## B01 Real Smoke Independent Audit

The existing directory was audited read-only. No provider was called and no raw
model text, hidden test body, or credential value was printed.

### Observed Outcome

- Eval: `success=false`, actor status `failed`, acceptance failed, task
  verification failed, regression passed, budget passed, security passed.
- Team artifact: control status `paused`, failure category `interrupted`.
- Node/Worker result: `paused`, category `no_source_progress`, attempt 1.
- Usage: 14 steps, 28 tool calls, 52,988 input tokens, 1,543 output tokens.
- Workspace: `changed_files=[]`, `workspace_version=0`, source progress count 0.
- `final.diff`: empty.
- Model evidence: 14 model outputs; 28 tool calls, including two `apply_patch`
  calls. Both patch tool results were identical failed results.

### Answers To Required Questions

1. **Was an effective patch generated?** No. There were two patch attempts, but
   both failed at the tool boundary; no patch was applied and the final diff is
   empty.
2. **Why `patch_attempts=2` with no source progress?** The metric counts attempted
   patch calls. Failed patch application does not increment workspace version or
   source progress. The Runtime then reached the deterministic no-source-progress
   pause guard.
3. **Are statuses consistent?** Yes at their respective layers: Worker PAUSED due
   to no source progress; Team PAUSED and classifies the stop as interrupted; Eval
   exposes a failed actor and failed external acceptance. No layer reports success.
   The Team category is coarser than the Worker category but the detailed cause is
   retained in node evidence and the error.
4. **Was the smoke manifest finalized?** No. It remains
   `real_llm_result="STARTED"`. Source inspection confirms the script writes
   `STARTED` before `run_suite` and never writes COMPLETED/FAILED afterward.
5. **Did hidden test content leak?** No leak evidence was found. Runtime messages
   contain no `eval_hidden` path, credential/API authorization marker, or hidden
   test body indicator. One generic phrase about hidden acceptance is policy text,
   not hidden test content. This finding is scoped to the inspected B01 artifacts.
6. **Failure classification:** Primary cause is model/tool-use capability: both
   patch applications failed and the Runtime's no-progress guard correctly paused.
   It is not evidence of a Scheduler/fencing/DAG corruption. A separate experiment
   evidence-state bug exists in the non-finalized manifest.
7. **Week6 blocker?** The stochastic B01 failure alone does not prove the Team
   architecture invalid, but the required single-Worker smoke gate is not met.
   Together with the deterministic P0/P1 findings below, Week6 entry is blocked.

## Production Defects And Findings

### P0 - Credential markers are persisted in Team artifacts

- Reproduction:
  `.venv/bin/python -m pytest tests/agent_team/test_day7_team_runtime_acceptance.py::test_team_artifacts_redact_credential_markers_from_worker_failures -q`
- Expected: exception/provider credential material is redacted before node/team
  artifact persistence.
- Actual: the synthetic credential marker is present in persisted JSON artifacts.
- Initial cause: `WorkerExecutor._failure_result` copies exception text verbatim;
  `TeamRunArtifactStore` serializes the complete node runtime result without a
  redaction boundary.
- Suggested boundary: central structured error sanitizer before mailbox/artifact
  publication, with regression coverage for error, messages, model outputs, and
  verification streams.

### P1 - Team common result trusts forged Worker workspace evidence

- Reproduction:
  `.venv/bin/python -m pytest tests/agent_team/test_day7_team_runtime_acceptance.py::test_team_result_does_not_trust_worker_reported_workspace_evidence -q`
- Expected: `changed_files`, diff, and verification are derived or verified at the
  coordinator/grader boundary, not accepted from an injected Worker result.
- Actual: an empty workspace produces a Team common result containing fabricated
  changed files, diff, and passed verification supplied by the Worker.
- Initial cause: `_aggregate_common_result` directly aggregates Worker result
  fields. The external grader still prevents this alone from proving final task
  success, but the Team artifact/common evidence is untrustworthy.
- Suggested boundary: coordinator-owned workspace diff/fingerprint and trusted
  verification evidence; mark Worker reports as claims until independently checked.

### P2 - Real smoke manifest remains STARTED after completion/failure

- Reproduction:
  `.venv/bin/python -m pytest tests/scripts/test_day7_smoke_manifest_acceptance.py -q`
- Expected: terminal manifest state (`COMPLETED` or `FAILED`) and final result
  metadata are atomically persisted after the runner returns.
- Actual: `real_llm_result` stays `STARTED`; the existing B01 artifact demonstrates
  the same stale state.
- Initial cause: `evals/week5/smoke_team_runtime.py` has no post-run/finally manifest
  write.

### P2 - Evidence documents are stale relative to the current B01 run

`DD-W5-07`, `DD-W5`, `W5_FAILURES`, and `W5_REPORT` still describe real B01 as
`NOT_RUN`. They correctly avoid overstating support, but no longer describe the
current failed smoke artifact. No document was modified because docs were read-only
inputs for this acceptance.

### P3 - Existing static hygiene debt

Ruff has one unrelated import-order issue; Mypy has the classified historical
errors above. Neither was introduced by the tester, but the repository-wide static
gate is not green.

## Design Decision Verification

- DD-W5-07 remains `PROPOSED`; this is appropriate because independent acceptance
  did not pass.
- Reuse of CodingRuntime, coordinator single-writer, bounded thread pool, shared
  writable-worktree denial, external grader authority, separate Team artifact,
  weighted budget, and capability gate are reflected in code and tests.
- The DD/report's B01 and experiment evidence statuses are stale, not exaggerated
  to SUPPORTED/ACCEPTED.
- Week6 boundaries remain explicit: no per-worker worktree, patch merge/conflict
  policy, reviewer gate, distributed workers, or external side-effect exactly-once.

## Benchmark And Ablation

### Deterministic Benchmark

- Status: **NOT_RUN (Correctness Gate failed)**.
- Requested output would have been
  `/tmp/week5-day7-acceptance-20260902/deterministic-team`.
- No raw samples, p50/p95, utilization, speedup, or parallel efficiency are reported
  because the independent correctness/security suite has three stable failures.
- No correctness-failing sample was admitted into a performance conclusion.

### Sequential/Parallel Ablation

- Status: **NOT_RUN**, because it is the 1-vs-3 Worker view of the blocked
  deterministic benchmark.
- Existing Barrier test proves overlap for one fan-out scenario, but it is not a
  substitute for the requested repeated experiment.
- Linear workload is not claimed to have parallel benefit.

### Single-vs-Team Comparison

- Status: **DESIGNED / NOT_RUN**.
- Plan output:
  `/tmp/week5-day7-acceptance-20260902/single-team-plan/comparison_plan.json`.
- Verified fields: `status=NOT_RUN`, architecture comparison rather than pure
  ablation, Week4 11-task suite marked dev/not held-out, and no fabricated scores.

### No-Mailbox

- Status: **NOT_RUN**. No functionally equivalent alternative transport adapter
  exists; removing Mailbox would not be a valid ablation.

## Failure Cases

- Duplicate claim, stale generation/runtime/attempt, retry exhaustion, blocked
  propagation, durable claim/ack, CAS poisoning, crash reconciliation, and shared
  writable-worktree denial have deterministic test evidence in the combined suite.
- New failure cases retained by this acceptance: untrusted Worker evidence,
  credential persistence, and non-finalized smoke manifest.
- B01 records a model/tool patch-application failure followed by a correct
  no-source-progress pause. It does not demonstrate a reproducible control-plane
  failure.
- Not fully verified here: Team-level commit-failure-before-ack injection, duplicate
  result replay through the complete Day7 publication path, stale active Future
  racing a new attempt, and final Team artifact publication failure recovery.

## Final Status

| Area | Conclusion |
|---|---|
| Test Development | COMPLETED: 10 independent cases added; 7 pass, 3 retain stable failures |
| Correctness | FAILED: untrusted Worker evidence violates the required result contract |
| Concurrency | PARTIAL: bounded overlap and control-plane suites pass; all benchmark DAG shapes not executed |
| Durability/Fencing | PARTIAL PASS: three-layer fencing and process resume pass; Day7 result commit/ack fault matrix is incomplete |
| Safety | FAILED: deterministic credential marker persistence is P0 |
| Evaluation Integration | PARTIAL PASS: common runner/grader and false-success prevention work; Worker evidence provenance is defective |
| Real B01 Smoke | FAILED: no effective patch; no-source-progress pause; manifest not finalized |
| Deterministic Benchmark | NOT_RUN: correctness gate failed |
| Sequential/Parallel Ablation | NOT_RUN |
| Single-vs-Team Comparison | DESIGNED / NOT_RUN |
| Week5 experiment completion | INCOMPLETE |
| Overall Day7 Acceptance | **NOT PASSED** |
| Week6 Entry Recommendation | **DO NOT ENTER WEEK6 YET** |

Required next work before re-acceptance:

1. Add a central redaction boundary for Team errors/messages/artifacts and make the
   retained P0 test pass.
2. Derive or independently verify changed files, diff, and verification evidence;
   make the retained P1 test pass.
3. Finalize smoke manifest terminal state and update stale evidence documents.
4. Add Team-level publication fault/replay tests.
5. Re-run the full correctness/static gates. Only after they pass, run the requested
   deterministic benchmark and sequential/parallel ablation.
6. Re-run a learner-authorized single-Worker B01 smoke without claiming success
   unless an effective patch and external acceptance both pass.
