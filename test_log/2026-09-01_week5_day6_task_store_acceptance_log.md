# Week5 Day6 TaskStore + Session Integration Independent Acceptance Log

## 1. Evaluation Summary

- Date: 2026-09-01 (Asia/Shanghai)
- Baseline time: 2026-09-01 15:17:40 +0800
- Completion time: 2026-09-01 18:01:03 +0800
- Branch: `week5`
- HEAD: `c39f0fb025c92e7cb9d261b0444add299a7a94da`
- Initial staged state: empty
- Initial worktree: mixed unstaged and untracked Day6 implementation; preserved as acceptance input
- Input drift during acceptance: none; all 60 baseline input SHA256 values matched at end
- Production/config/document changes by tester: none
- New tester files: 2 tests/helpers plus this new log
- Benchmark/Ablation: `NOT_RUN` as required
- Final Day6 conclusion: **FAIL**
- Day7 recommendation: **do not enter Day7 before P0/P1 findings are fixed and independently rerun**

The coder's original eight-file suite passes, but it does not exercise the public
durability bypass. Independent tests demonstrate that live Registry, Scheduler,
Mailbox and Lifecycle state can change while SQLite remains at the old revision.
This violates the central Day6 claim that `DurableTeamRuntime` is the only
supported mutation/persistence gateway.

## 2. Capability Mapping

Primary capability:

- Multi-Agent Orchestration: durable Task DAG, ownership, Worker state and Mailbox.
- Agent Runtime: process-crash reconstruction, runtime epoch fencing and fail-closed resume.

Secondary capability:

- Observability: state and event history in one SQLite transaction.
- Workspace/Git: reconcile external code effects before replay.
- Safety: path boundary, symlink rejection and single-writer ownership.

What must be proven:

1. Every acknowledged Team mutation crosses the durable commit boundary.
2. Invalid snapshots cannot enter SQLite or hydrate a live runtime.
3. State/event/CAS remain atomic under exceptions, process exit and concurrency.
4. Resume creates a new runtime epoch and reconciles Session, Team and Git.
5. Storage paths cannot escape the protected Session directory.

## 3. Repository Baseline

The initial `git status --short --branch --untracked-files=all` showed branch
`week5...origin/week5`, no staged files, and existing unstaged/untracked Day6
production, tests, docs and coder log. Tester did not stage, commit, merge, switch
branches, create a worktree, push, reset or clean.

Environment:

- Python: 3.11.15 via `.venv/bin/python`
- SQLite: 3.53.3
- Platform: macOS-26.5.2-arm64-arm-64bit
- Pytest config: `testpaths = tests`, `norecursedirs = tests/fixtures`

Files inspected:

- `.codex/AGENTS.md`, `prompt/test_Agent.md`, `pytest.ini`
- `learning-plan/week5/day6.md`, `learning-plan/week5/week5_plan.md`
- `docs/design_decisions/DD-W5-06.md`
- `docs/failure_cases/W5_TASK_STORE_FAILURE.md`
- `docs/benchmark/W5_TASK_STORE.md`
- `test_log/2026-09-01_week5_day6_task_store_log.md`
- all files under `codeteam/agent_team/`, `codeteam/session/`,
  `tests/agent_team/` and `tests/session/`

## 4. Tester File Changes

Added:

- `tests/agent_team/test_day6_task_store_acceptance.py`
  - 16 collected acceptance cases.
  - Direct mutation bypass, gateway completeness, no-op revision, poison behavior,
    durable contract negatives, event drift, DB symlink and real two-process claim.
- `tests/agent_team/day6_acceptance_process_helper.py`
  - Real subprocess contender for one durable Mailbox claim.
- `test_log/2026-09-01_week5_day6_task_store_acceptance_log.md`
  - This independent evidence report.

No existing test was weakened or modified. No skip/xfail was added.

## 5. Requirement Matrix

| ID | Requirement | Implementation/Test Evidence | Status |
| --- | --- | --- | --- |
| R1 | Session/Team/Git authority does not overlap | DD and modules separate stores; Session has only Team revision hint | PASS (design) |
| R2 | All Day5 mutation paths use DurableTeamRuntime or are prohibited | Direct calls through public `scheduler`, `registry`, `mailbox`, `lifecycle` mutate live state while DB is unchanged | **FAIL / P0** |
| R3 | schedule/claim/start/complete/fail/heartbeat/stop/send/claim/ack/release durable path | Wrappers exist for these named paths; original claim/start/complete and Mailbox tests pass | PARTIAL |
| R4 | restart/sweep durable path | `DurableTeamRuntime` has no `restart_worker` or `sweep`; mutable lifecycle remains public | **FAIL / P0** |
| R5 | Durable contract excludes ephemeral objects and non-JSON payloads | Existing model tests pass | PASS |
| R6 | Cycle/unknown/self/duplicate DAG rejected before persistence | Unknown/self/duplicate covered; cyclic dependencies are accepted and persisted | **FAIL / P1** |
| R7 | Worker key/identity and ownership consistency | Ownership generation test passes; worker map key may differ from embedded identity | **FAIL / P1** |
| R8 | READY/waiting/ownership invariants | Existing parameterized model tests cover duplicate/missing queue and ownership | PASS |
| R9 | Message identity/order/claim/dedupe invariants | Existing model/store tests plus two-process claim; modified delivery attempt rejected | PASS for tested V1 claim/ack boundary |
| R10 | NaN/Inf/non-JSON/naive datetime rejected | JSON and aware datetime covered; Task `claimed_at` accepts NaN/+Inf/-Inf | **FAIL / P1** |
| R11 | initialize/load/commit, CAS, state+event transaction | Original tests and `os._exit(91)` crash test pass | PASS for selected crash point |
| R12 | Event seq/revision/last_event_seq alignment | Normal writes align; manual event revision drift is silently accepted on load | **FAIL / P1** |
| R13 | Missing/corrupt/future schema never falls back to empty Team | Existing missing/corrupt/future schema tests pass | PASS |
| R14 | DB/session symlink and protected path boundary | Session-dir symlink rejected; existing DB symlink is followed and external target modified | **FAIL / P1 Security** |
| R15 | Owner-only DB/WAL/SHM permissions | Main DB/session modes covered; WAL/SHM mode persistence not independently exhaustive | PARTIAL |
| R16 | No-op does not advance durable revision | No-op `runtime.schedule()` advances revision and timestamp | **FAIL / P2** |
| R17 | Persistence failure poisons runtime and preserves old DB | New fault-injection test passes; subsequent mutation fails closed | PASS |
| R18 | Concurrent CAS/no lost update | Existing CAS tests plus real two-process same-message claim: one claim, one conflict | PASS for local single-writer case |
| R19 | New epoch rejects old WorkerLease/TaskClaim/MessageClaim | Existing hydration/reconciliation tests cover Worker/Task; Mailbox matching fields covered | PASS/PARTIAL |
| R20 | Preserve generation/attempt/restart budget/queue/dedupe/UTC deadline | Existing hydration and reconciliation tests pass | PASS for represented states |
| R21 | All seven Task states reconciliation matrix | RUNNING/CLAIMED recovery, retry exhaustion and descendants covered; complete seven-state matrix is absent | PARTIAL |
| R22 | Unknown Git effect/active operation fails closed without Team rewrite | Existing dirty-worktree subprocess and reconciliation tests pass | PASS for tested dirty effect |
| R23 | Resume order and revision gap handling | Team-ahead/behind, missing DB/builder and double-resume tests pass | PASS for selected windows |
| R24 | Real process crash boundaries | SQLite mid-transaction, direct Team-commit gap and Git dirty exit exist; exact crash inside Session save/event publication remains partial | PARTIAL |
| R25 | Two real processes resume only one writer | Existing double-resume subprocess test passes | PASS |
| R26 | Successful resume/pause/releases lock/new process resume | Lock release and double-resume components covered; complete sequential new-process scenario not one test | PARTIAL |
| R27 | Ruff | All touched scope checks pass | PASS |
| R28 | Direct mypy target works | Duplicate module mapping on Day6 helper blocks checking | **FAIL / P2** |
| R29 | Full regression | 14 independent Day6 failures | FAIL |
| R30 | Docker regression | Initial sandbox run skipped 9 for socket permission; authorized rerun passed all 71 | PASS after escalation |
| R31 | Benchmark/Ablation | Plan exists; no run or numbers required today | NOT_RUN |

## 6. Test Execution Results

| Command | Exit | Passed | Failed | Skipped | Errors | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `.venv/bin/python -m pytest tests/agent_team/test_team_state_models.py tests/agent_team/test_sqlite_team_state_store.py tests/agent_team/test_team_reconciliation.py tests/agent_team/test_team_hydration.py tests/agent_team/test_team_store_process_crash.py tests/session/test_team_runtime_resume.py tests/session/test_team_double_resume.py tests/session/test_team_resume_process_crash.py -q` | 0 | 44 | 0 | 0 | 0 | PASS |
| `.venv/bin/python -m pytest tests/agent_team tests/session -q` | 1 | 496 | 14 | 0 | 0 | FAIL |
| `.venv/bin/python -m pytest tests/git tests/execution -q` | 0 | 204 | 0 | 0 | 0 | PASS |
| `.venv/bin/python -m ruff check codeteam/agent_team codeteam/session tests/agent_team tests/session` | 0 | n/a | n/a | n/a | n/a | PASS |
| `.venv/bin/python -m mypy codeteam/agent_team codeteam/session tests/agent_team tests/session` | 2 | n/a | 1 diagnostic | n/a | n/a | FAIL before checking |
| `.venv/bin/python -m mypy --explicit-package-bases codeteam/agent_team codeteam/session tests/agent_team tests/session` | 1 | n/a | 71 diagnostics / 11 files | n/a | n/a | FAIL |
| `.venv/bin/python -m pytest -q` | 1 | 1838 | 14 | 9 | 0 | FAIL |
| `.venv/bin/python -m pytest tests/sandbox -q -rs` | 0 | 62 | 0 | 9 | 0 | ENVIRONMENT SKIP |
| authorized rerun of the same sandbox command | 0 | 71 | 0 | 0 | 0 | PASS |
| `git diff HEAD --check` | 0 | n/a | 0 | n/a | n/a | PASS |

Additional tester preflight:

- `.venv/bin/python -m pytest tests/agent_team/test_day6_task_store_acceptance.py -q`
  consistently produced `2 passed, 14 failed`.
- Narrow mypy with `--explicit-package-bases --follow-imports=skip` over six Day6
  production files and the two new tester files: `Success: no issues found in 8 source files`.

## 7. Mypy Classification

### Day6 regression

**P2**: direct command is blocked by:

```text
tests/agent_team/team_state_helpers.py: error:
Source file found twice under different module names:
"agent_team.team_state_helpers" and "tests.agent_team.team_state_helpers"
```

This is a current Day6 test-package/module-layout regression, not historical debt
and not an environment failure.

### Historical/import-chain diagnostics with explicit package bases

The alternate command reports 71 diagnostics in 11 files:

- Missing third-party stub: 1 in `codeteam/instructions/frontmatter.py` (PyYAML).
- Existing parser types: 3 in `codeteam/parsing/tree_sitter_parser.py`.
- Existing file-tool types: 9 in `codeteam/tools/files.py`.
- Existing failure-model types: 2 in `codeteam/failures/`.
- Existing search types: 10 in `codeteam/search/ripgrep.py`.
- Existing sandbox type: 1 in `codeteam/sandbox/environment_inspection.py`.
- Existing LLM types: 34 in `codeteam/llm/openai_compatible.py`.
- Existing orchestrator types: 8 in `codeteam/agent/orchestrator.py`.
- Existing enum-construction tests: 3 in `tests/agent_team/test_models.py` and
  `tests/agent_team/test_dag.py`.

No diagnostic in the six new Day6 production modules or the tester's two new files
was reported by the narrow direct-file audit.

## 8. Confirmed Findings

### P0: Durable gateway can be bypassed through public mutable components

Reproduction:

```bash
.venv/bin/python -m pytest   tests/agent_team/test_day6_task_store_acceptance.py::test_public_component_reference_cannot_bypass_durable_gateway -q
```

Expected: direct component mutation is unavailable/prohibited, or it commits the
same transition and event to SQLite before success is returned.

Actual: direct Scheduler claim, Registry heartbeat, Mailbox send and Lifecycle stop
all change live state while SQLite revision and snapshot remain unchanged.

Impact: a later process crash reloads stale durable state and may lose ownership,
heartbeat, stop or message facts. This invalidates the central Day6 durability
boundary and can lead to duplicate execution or stale replay.

Suspected root cause: `DurableTeamRuntime` publicly exposes mutable component
objects whose existing public methods remain callable.

### P0: Lifecycle restart/sweep lack durable gateway methods

Reproduction:

```bash
.venv/bin/python -m pytest   tests/agent_team/test_day6_task_store_acceptance.py::test_durable_gateway_covers_lifecycle_mutations -q
```

Expected: all Day5 mutating lifecycle paths are routed through persistence or
explicitly disabled in durable runtime mode.

Actual: no `DurableTeamRuntime.restart_worker` or `sweep`; callers can only use
the exposed mutable lifecycle object and bypass persistence.

### P1: Invalid durable graph/identity/numeric state can be stored

Reproduction:

```bash
.venv/bin/python -m pytest   tests/agent_team/test_day6_task_store_acceptance.py::test_snapshot_rejects_cycle_before_store_initialization   tests/agent_team/test_day6_task_store_acceptance.py::test_snapshot_rejects_worker_key_identity_mismatch   tests/agent_team/test_day6_task_store_acceptance.py::test_snapshot_rejects_non_finite_task_timestamp -q
```

Actual:

- cyclic dependencies are accepted and a SQLite DB is created;
- Worker map key can differ from `AgentInfo.identity.agent_id`;
- Task `claimed_at` accepts NaN and positive/negative infinity.

Impact: invalid durable state can survive until hydration or later serialization,
turning a boundary validation error into recovery failure or non-portable storage.

### P1 Security: database-file symlink escapes the Session storage boundary

Reproduction:

```bash
.venv/bin/python -m pytest   tests/agent_team/test_day6_task_store_acceptance.py::test_database_symlink_is_rejected_without_touching_target -q
```

Expected: reject the `team_state.sqlite3` symlink and preserve the target SHA256.

Actual: SQLite follows the symlink and rewrites the external target. The target
SHA256 changes from the empty-file digest to a populated SQLite database digest.

### P1: Event/meta drift is not detected during load

Reproduction:

```bash
.venv/bin/python -m pytest   tests/agent_team/test_day6_task_store_acceptance.py::test_load_detects_event_cursor_and_revision_drift -q
```

Expected: event revision/sequence and `last_event_seq` are validated against the
snapshot meta before accepting the Team state.

Actual: an event row manually changed to revision 999 is silently accepted by
`load()`; state and audit history can disagree without a corruption error.

### P2: No-op schedule creates a new durable revision

Reproduction:

```bash
.venv/bin/python -m pytest   tests/agent_team/test_day6_task_store_acceptance.py::test_noop_schedule_does_not_advance_durable_revision -q
```

Expected: no business-state/event change means no revision change.

Actual: `runtime.schedule()` reports no newly scheduled task but commits a new
revision and timestamp.

### P2: Direct mypy command is blocked by duplicate module discovery

See the mypy classification above. The fallback command is useful for diagnosis
but does not make the required direct command pass.

### P3

No P3 finding was confirmed.

## 9. Passing Evidence

- Poison-on-persistence-failure: in-memory claim followed by injected commit failure
  does not return success, old SQLite snapshot remains readable, runtime is poisoned,
  and later mutation is rejected.
- Real two-process Mailbox claim: exactly one process claims the message and one
  receives revision conflict; durable revision becomes 2 with one IN_FLIGHT message.
- Real `os._exit(91)` during SQLite transaction: old snapshot/events remain intact.
- Two-process Session writer exclusion passes.
- Old runtime Worker/Task tokens are rejected in represented hydration tests.
- Dirty Git effect after process exit produces `RECOVERY_REQUIRED`.
- Authorized Docker rerun passes all 71 sandbox tests.

These results support selected local, single-host failure boundaries only.

## 10. Failure Cases and Unverified Scope

Not fully verified:

- complete seven-status reconciliation matrix with complex renamed/disconnected DAGs;
- every Day5 mutator, especially durable restart/sweep publication races;
- exact process exit inside Session `save(RUNNING)` or event append after a real
  Team runtime build (existing process test commits Team directly, then exits);
- disk full, fsync failure, WAL checkpoint interruption and persistent WAL/SHM modes;
- bounded busy timeout under a deliberately held cross-process write lock;
- arbitrary SIGKILL instruction points;
- real external Worker processes;
- external Git/command side-effect exactly-once;
- distributed database, cross-machine scheduling or multi-primary ownership.

No real LLM/API, benchmark or ablation was run.

## 11. Benchmark and Ablation

Status: **NOT_RUN / DESIGNED**.

The plan defines 100/500/1000 Task workloads, cold/warm separation,
`T_load`, `T_reconcile`, `T_hydrate`, `T_persist`, and
`T_recovery_ready`, plus normalized SQLite, memory-only, JSON/blob and event
history variants. No numbers, raw samples or performance claims exist, so DD-W5-06
performance evidence remains `INSUFFICIENT_EVIDENCE`.

## 12. Design Decision Verification

Decision: normalized SQLite snapshot + append-only event history, new runtime
epoch, claim/ack Mailbox and fail-closed Session/Git reconciliation.

Evaluation: **PARTIALLY_SUPPORTED**.

Supported:

- selected CAS, transaction rollback, process crash, message claim and writer-lock cases;
- new runtime hydration and represented old-token fencing;
- DB-ahead/behind Session handling and dirty Git fail-closed.

Not supported:

- claim that `DurableTeamRuntime` is the enforced mutation boundary;
- complete durable contract/schema gate;
- DB symlink path boundary;
- event/meta consistency gate;
- benchmark/ablation value or performance.

## 13. Dimension Conclusions

| Dimension | Conclusion |
| --- | --- |
| Functional | PARTIAL: core store/resume happy paths work; independent contract failures remain |
| Durability | FAIL: direct live mutation bypasses SQLite |
| Recovery | PARTIAL: selected crash windows pass; matrix and publication crash points incomplete |
| Concurrency | PARTIAL/PASS for tested single-host CAS, Mailbox claim and writer lock |
| Security | FAIL: DB-file symlink writes outside intended Session file |
| Static | FAIL: required mypy command blocked by Day6 duplicate-module regression |
| Regression | FAIL: full suite has 14 Day6 acceptance failures |
| Docker | PASS after authorized rerun, 71/71 |
| Benchmark/Ablation | NOT_RUN / DESIGNED |

## 14. Final Conclusion

Week5 Day6 does **not** pass independent acceptance.

The local SQLite implementation contains useful, passing pieces, but the central
durability claim is not enforceable while callers can mutate public runtime
components outside `DurableTeamRuntime`. P0/P1 findings must be fixed before
Week5 Day7 integration, then the failure-specific tests, target suites, full suite,
Ruff and both mypy commands must be rerun.

## 15. Baseline SHA256 Manifest

All values below were captured before tester edits and matched at end of execution:

```text
28ec41cba8fc8757c58ac6fdcd7a74f1724c1a33486c5b4e614b51250f1c4922  .codex/AGENTS.md
09d56dd38c8d7446092fb5d6707aff67c2c50d0e06ff89b794ff57305654327d  prompt/test_Agent.md
5f679eaef68016eebe3533f218b9db24ff44244451395643f45ab2d2518c51b6  pytest.ini
b9afb3c17d7a5ffcbe8d78bd5f95e8db916279992ee7752ca991ec6313fbcb26  learning-plan/week5/day6.md
8c4db7af5cc95792ed8bd0f8883dd9adfa64d9d7ea6968c43743dca2f5e4ecdf  learning-plan/week5/week5_plan.md
85df68d8efdc873c1c478d1b7215ed8ede884bf24711eaa17a5c4256cb192b11  docs/design_decisions/DD-W5-06.md
7f1b83a34a031912cad459b0d6422ad7a08cd8e7e51a4b43179286702273c08e  docs/failure_cases/W5_TASK_STORE_FAILURE.md
0e436ba1e94e97def22544d83a9fddbe918b022d87982518f92b9dd1d51fc630  docs/benchmark/W5_TASK_STORE.md
14885789d3b75331575c5f0a5b974ff6777cfb1ddbc08b90bdb80bcb4789d4c2  test_log/2026-09-01_week5_day6_task_store_log.md
a183dfbdb2a6c411b51445dbcc99d137d688e7200dea6ae531688e7b38dad34b  codeteam/agent_team/__init__.py
f0b63411b14bddf998922b69f47f2978148feec280a45b5fb832bcb10d5eb671  codeteam/agent_team/contracts.py
3f510e8bc63fa9fe625be8bf199a654b16f32532caf2fd58844d16f4df8dad38  codeteam/agent_team/coordination.py
d6faf8f7064ee3160b9d1545d63febc91b8f8412a0e5ba897d189ed74038c4f7  codeteam/agent_team/dag.py
6345c57d0295d87766808cf544add2e72de4fba4675c1317668b2397f23540fd  codeteam/agent_team/lead.py
b6ac735131bee42402c38a3b90921b53f276f855f5b4b76f274eb5d2b6906f3b  codeteam/agent_team/lifecycle.py
fc5c13467abc65e29194611131280cf80b040dec5bc3389975d6bbfdfc9ca0c3  codeteam/agent_team/mailbox.py
dd6cafff7d488f3ff9e8227d56e38148ab44980e13dfb9029fe7b50ed6090317  codeteam/agent_team/models.py
ce6d8f39efae46b23f3df169045488ae7838276ef47d2af65295474bb0e7ba8c  codeteam/agent_team/persistence_errors.py
69b4ce558e5a566831d0220fa335e9a6438cab7848035777e773b34a4ae76f01  codeteam/agent_team/persistence_models.py
05c2e31484204116806b8a84433b882518af96cacd405d6b88a94d1e9c86384d  codeteam/agent_team/reconciliation.py
2fd5104d6e377cf1d306afb7167e1260708af7edd3e0bad9172a6ddfbb168089  codeteam/agent_team/registry.py
f8eaa7f12337134456a3cc75791d6481d0cf10d6b79ba75523b4351ce6c85e96  codeteam/agent_team/runtime_factory.py
9fb6f5eb3372e53fa1e1765ddd179eb9a21331b84484d465ba1a16eb571d6358  codeteam/agent_team/scheduler.py
17862086b54afd8dc89f71fa6dab25e098f83b1ac73869a7a2fe224d967135af  codeteam/agent_team/session_integration.py
b7df22aed0f1a7cec2b38c2c97d76340acd956ee30f7169ca69a3e5a78dc15ea  codeteam/agent_team/team_store.py
f352b86f7229e9452b6fd72eb9bdaf4e6f9b5abf540b3455f9b3d0559d393b0c  codeteam/agent_team/worker.py
8944fd4cd32909f952f6d488d8b231d78ba238002c55a6479193f6ea9e40dfd9  codeteam/session/__init__.py
2842af1d0ffaf7f2729d0675d84aa8affc267bf3f5517dfaaf31bee46deb8a12  codeteam/session/errors.py
b05f10004814dd36b1f4d46183f0742225e1c27b72fce7cd9ad18faa372f1c26  codeteam/session/models.py
9dfc4426d7b7d3eee694c3163b65945d56969062fb788be58cffbebdd8024fac  codeteam/session/service.py
0d7ac7ceefca7104eda67d889893078509093097a10063309bca7979bd4f7abf  codeteam/session/store.py
01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b  tests/agent_team/__init__.py
bdfa8aa16ca7d6774696ee68d6aa01627e56f7ee36c1714835e9fc0000d43890  tests/agent_team/team_process_helper.py
dfdb45689bba621e081c971b1c31a808aea8c4355d9ddfefd8909e22d603722f  tests/agent_team/team_state_helpers.py
fed393b77cf77a318abdc4fb508db5af331ac68792346925f71f45948f3f9693  tests/agent_team/test_dag.py
7eeeac0b3fb17b04099855246c8dfe500ba12c1eea97e42cb18fb2f864733966  tests/agent_team/test_fencing.py
0115ceb925785e2f50c36044f8f8c771c8de625f7d866e0354999b82515480c0  tests/agent_team/test_lead.py
2e55f7a659cc5445f9c34a6044eff09528a7b3e2925badd740defee7e6333b25  tests/agent_team/test_lifecycle.py
415c3bf2e0cf2a099aabca1b8ecedab3f24bb10c67fb17df46228fa9d7bdb599  tests/agent_team/test_lifecycle_acceptance.py
0e9e85ec2e1acf065da505b65f1c1d3999444bf796af5fe4e59d074b3c16e1d5  tests/agent_team/test_lifecycle_fixes.py
20505561e2c6b1f8d7650b049f563a0bf341f4f038518f5b4532e47450050311  tests/agent_team/test_mailbox.py
ff22deac7f17b8a9e88545b3f79fb9b33a04e7205cd8904bb96e76dd3da86c60  tests/agent_team/test_models.py
2b625b4382ca7fb78578b03b70566f10e16a8715fe4d0411b84223ada4b91dd8  tests/agent_team/test_registry.py
f80bd4740e188d76b9c55d24e777972d6964a7350687514a060eaf83e9b71a4c  tests/agent_team/test_scheduler.py
81bc2736fda0fabe34455da5ac10fd986e4ab8ed5acc428c88dfbda0d45ca21b  tests/agent_team/test_sqlite_team_state_store.py
3c4e0bc899448b913126b9d03e0fda22dae20033c448ee12f4c3d97e43151dd4  tests/agent_team/test_team_hydration.py
8dfc7872668b4672aba2c0a67ca5e1a86a8f262a32d5540d779e66a03855907d  tests/agent_team/test_team_reconciliation.py
400f1100c5d490fa49d3207b60b2482217e1a6145889193867e254708f2f2317  tests/agent_team/test_team_state_models.py
837954bec1b99b9a9d05ab23e0641f8668bcfdc638b37b8b437112eaf7647a90  tests/agent_team/test_team_store_process_crash.py
7027bf1b977904bbd2e1c3c6693a6eb1ce8b8ba69077ba61df2d24d1219b7016  tests/agent_team/test_worker.py
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  tests/session/__init__.py
71cdd415bc7f5924e1c72fbe9b28de2e0ac45581beef2eb2ef70fcea1f7ff73b  tests/session/conftest.py
b85eb0fe9d1ad24da726d53e607cd7f1a9f40906dceef601bee0bc4f32fc5983  tests/session/test_day4_durable_contract.py
ccc5d95e74179d0c45fcbc97bdb862e19f1c6aed63d00477a84cb780c795780e  tests/session/test_day4_pause_reconcile_resume.py
7a6c9477c47f50a2ac0774552534d82d84e2bae4887666c7601c742f999670d5  tests/session/test_day4_store_events.py
245e0a03e2d94c9b54e647e605d00bc4ea9fff0456145416c1f0cfc5bb83c3af  tests/session/test_native_turn_resume.py
8d6fa36e977662a7616431c8c854ce330228f17728806d3ddedf6778b4ec66ee  tests/session/test_step0_state_gates.py
45826af338ad10b344b50ec38f775354b59996f1010862ca5422918a5c79ff61  tests/session/test_team_double_resume.py
d3eb3edaf780a83482371f7dfd3228d4959b85f685cca01ecf3dd5fed82bed6a  tests/session/test_team_resume_process_crash.py
cdcdbb86c12e427c0a36794718c62c8decdc5becd1a5b83cf6ef96529a859958  tests/session/test_team_runtime_resume.py
```

