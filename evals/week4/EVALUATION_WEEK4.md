# Week 4 Day 7 Evaluation Report

Date: 2026-08-23

Original closeout state: `101d95b`. The task-suite correction recorded on
2026-08-25 uses unified fixture commit
`3956afc05d6c1ad2f3efaac9a510133436c0f700` plus verified per-task seed patches.

This report is a four-week closeout evaluation, not a claim that CodeTeam is already a full autonomous coding benchmark runner. The current CLI can inspect, retrieve context, create durable sessions, pause/resume, diff/rollback, enforce command policy, execute Docker sandbox checks, and run a task-level agent-eval harness. The production `codeteam run` path still uses a deterministic `MockPlanner` shell; real patch generation now exists in the independent evaluation path as `LLMPatchGenerator` + `PatchActor`.

## Reproducibility

All commands were run with `.venv/bin/python`.

Key configuration:

| Field | Value |
|---|---|
| Python command | `.venv/bin/python` |
| Agent task baseline commit | `3956afc05d6c1ad2f3efaac9a510133436c0f700` |
| Retrieval Top K | 5 |
| Retrieval methods | `filename,ripgrep,ripgrep_symbol,hybrid` |
| Week2 dataset | `evals/week2/file_retrieval.jsonl` |
| Medium dataset | `evals/medium_repo/file_retrieval.jsonl` |
| Week4 task suite | `evals/week4/agent_task_suite_v1.jsonl` |
| Hidden oracle V1 | `eval_hidden/week4/` |
| Agent eval outputs | `evals/week4/agent_runs/` |
| Real LLM smoke | local sandbox DNS failed; elevated network call rejected by egress approval policy |
| Docker boundary | passed with elevated terminal access |

## Executed Commands

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/cli tests/session tests/sandbox tests/execution tests/git -q
.venv/bin/python -m pytest tests/sandbox -q -rs
.venv/bin/python -m codeteam.cli.app eval --dataset evals/week2/file_retrieval.jsonl --repo tests/fixtures/test_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output evals/week4/week2_retrieval
.venv/bin/python -m codeteam.cli.app eval --dataset evals/medium_repo/file_retrieval.jsonl --repo tests/fixtures/medium_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output evals/week4/medium_retrieval
.venv/bin/python evals/evaluate_day4.py
.venv/bin/python evals/w4d1_llm_smoke.py
.venv/bin/python -m codeteam.cli.app agent-eval --suite evals/week4/agent_task_suite_v1.jsonl --output evals/week4/agent_runs/null_baseline --actor null --mode baseline --keep-workspaces
.venv/bin/python -m codeteam.cli.app agent-eval --suite evals/week4/agent_task_suite_v1.jsonl --output evals/week4/agent_runs/null_ablations --actor null --mode ablations
.venv/bin/python -m codeteam.cli.app agent-eval --suite evals/week4/agent_task_suite_v1.jsonl --output evals/week4/agent_runs/llm_smoke --actor llm --mode baseline --limit 1
```

## Regression Results

| Check | Result | Notes |
|---|---:|---|
| Full pytest, normal sandbox | `1195 passed, 6 skipped` | Docker skipped because default sandbox cannot access Colima socket. |
| Full pytest, elevated terminal | `1198 passed` | Prior closeout run before agent-eval tests; Docker integration executed; no skips. |
| Focused Week3/Week4 runtime tests | `314 passed, 6 skipped` | CLI, session, sandbox, execution, git; skips are Docker-only in normal sandbox. |
| Docker sandbox boundary, elevated | `42 passed` | Workspace read/write succeeds; host secret, network, root FS write, socket checks pass. |
| CLI tests | included in full run | Invalid `--format` now exits 2 without traceback; SIGINT pause/resume E2E covered. |
| Session tests | included in full run | Durable session, event log, pause/reconcile/resume, secret redaction covered. |

## Retrieval Evaluation

### Week2 Test Repo

Output: `evals/week4/week2_retrieval/`

| Method | Recall@5 | Hit@5 | Errors | Empty Predictions |
|---|---:|---:|---:|---:|
| filename | 0.472 | 0.593 | 0 | 10 |
| ripgrep | 0.969 | 1.000 | 0 | 0 |
| ripgrep_symbol | 0.969 | 1.000 | 0 | 0 |
| hybrid | 1.000 | 1.000 | 0 | 0 |

Interpretation: the small Week2 fixture is now a smoke/regression suite. It proves that the retrieval pipeline, manifest generation, and method ablation execute correctly, but it is too small and too aligned with the implementation to stand alone as a robust benchmark.

### Medium Repo

Output: `evals/week4/medium_retrieval/`

| Method | Recall@5 | Hit@5 | Errors | Empty Predictions |
|---|---:|---:|---:|---:|
| filename | 0.325 | 0.400 | 0 | 6 |
| ripgrep | 0.667 | 0.700 | 0 | 4 |
| ripgrep_symbol | 0.686 | 0.733 | 0 | 4 |
| hybrid | 0.653 | 0.700 | 0 | 4 |

Hybrid misses concentrate in `business_behavior`, `cross_module`, and docs/config cases. This is useful evidence: current retrieval is strong for exact symbol and direct text matches, but weaker when a natural-language task must map business behavior to several indirect implementation files.

Representative misses:

| Case | Category | Missed Gold Files |
|---|---|---|
| `med-biz-001` | business_behavior | `src/auth/api.py`, `src/auth/exceptions.py`, `src/auth/service.py`, `tests/auth/test_refresh_flow.py` |
| `med-biz-003` | business_behavior | `configs/retry_policy.toml`, `src/billing/retries.py` |
| `med-biz-006` | business_behavior | `src/billing/webhooks.py`, `src/common/events.py`, `src/notifications/dispatcher.py` |
| `med-crs-001` | cross_module | `src/billing/invoices.py`, `src/billing/webhooks.py`, `src/common/events.py` |
| `med-doc-001` | instruction_config_docs | `docs/generated-code-policy.md` |

## Legacy Retrieval Smoke

`evals/evaluate_day4.py` still runs and writes `artifacts/search_results.json`.

| Method | Average Recall | Hit Rate |
|---|---:|---:|
| filename | 26.67% | 40.00% |
| ripgrep | 100.00% | 100.00% |
| symbol | 46.67% | 60.00% |

This 5-case script is retained as a historical smoke test. The newer CLI eval with manifest is the preferred benchmark path.

## Real LLM Smoke

`evals/w4d1_llm_smoke.py` was attempted earlier using local `secrets.local.env`.

Earlier attempts reached the model path and failed with:

```text
model_overloaded: 模型服务暂时繁忙，正在重试。 [max_attempts_exhausted] (来源: URLError)
```

The new `codeteam agent-eval --actor llm --limit 1` path was also attempted. In the managed sandbox it failed before reaching the provider:

```text
URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>
```

An elevated retry was requested, but the runtime approval review rejected it because the command would send repository task/context data to an external LLM endpoint whose concrete destination had not been explicitly approved in this turn. This is recorded as `BLOCKED_BY_APPROVAL/API_EGRESS`, not as a local implementation failure.

## 11-Task Agent Evaluation Status

The corrected suite is stored at `evals/week4/agent_task_suite_v1.jsonl`; hidden
oracles are stored under `eval_hidden/week4/`. Four tasks that evaluated the
CodeTeam repository itself (`F02`, `M01`, `M02`, `M03`) were removed. Every
remaining task evaluates only `tests/fixtures/medium_repo` from one fixed base
commit. `B01`, `B02`, and `B04` apply hash-pinned fault seeds after the common
archive is created; the other eight use the archived base directly.

| Split | Count | Purpose |
|---|---:|---|
| Development | 4 | Debug/tune harness, prompts, retrieval, repair. |
| Held-out | 7 | Freeze-before-run evidence. |

| Type | Count |
|---|---:|
| Bug fix | 5 |
| Feature | 3 |
| Refactor | 3 |

The runner now fails closed when a declared base commit cannot be archived,
verifies each setup patch SHA-256, commits the seeded baseline before the actor
runs, and records all base/seed metadata in the run manifest.

Corrected null preflight output: `evals/week4/agent_runs/null_baseline_v2/`.

| Actor | Mode | Tasks | Success | Provider Blocked | Acceptance Passed | Regression Passed |
|---|---|---:|---:|---:|---:|---:|
| null | baseline | 11 | 0 | 0 | 0 | 11 |
| Codex manual reference | baseline | 11 | 11 | 0 | 11 | 11 |

The null result proves every pristine task fails its hidden acceptance while
all public regression suites pass. The Codex reference run is stored at
`evals/week4/agent_runs/codex_reference_20260825/`; all 11 tasks passed hidden
acceptance, public regression, budget, and security checks. This is a
non-blind reference run because Codex inspected the hidden tests while repairing
the suite. It proves solvability and oracle discrimination, not held-out model
performance.

The earlier real-LLM runs targeted the obsolete 15-task suite and must not be
compared directly with V2. A fresh blind real-LLM baseline is still required.

## Ablation Status

| Ablation | Status | Current Evidence |
|---|---|---|
| Retrieval methods | RUN | `filename` / `ripgrep` / `ripgrep_symbol` / `hybrid` results above. |
| Docker sandbox boundary | RUN | Elevated full pytest and sandbox integration passed. |
| CLI invalid format / SIGINT resume | RUN | Covered by subprocess tests. |
| Plan-first vs direct execute | HARNESS_RUN_NULL_ACTOR | `null_ablations/direct_execute`; real comparison blocked until LLM egress is approved. |
| Repair loop vs single shot | HARNESS_RUN_NULL_ACTOR | `null_ablations/single_shot`; runner has a grader-driven repair loop, but null actor cannot demonstrate lift. |
| Structured compaction vs no/naive compaction | HARNESS_RUN_NULL_ACTOR | `null_ablations/no_compaction` and `null_ablations/naive_compaction`; current PatchActor records compaction mode but does not yet run long multi-turn compaction traces. |

Null ablation outputs:

| Mode | Tasks | Success | Provider Blocked | Acceptance Passed | Regression Passed |
|---|---:|---:|---:|---:|---:|
| direct_execute | 15 | 0 | 0 | 4 | 14 |
| single_shot | 15 | 0 | 0 | 4 | 14 |
| no_compaction | 15 | 0 | 0 | 4 | 14 |
| naive_compaction | 15 | 0 | 0 | 4 | 14 |

## Failure Cases

| ID | Status | Component | Observation | Next Action |
|---|---|---|---|---|
| W4-F001 | OPEN | Retrieval | Medium business/cross-module queries often miss indirect gold files. | Improve semantic query expansion, dependency fanout, and config/doc seeding. |
| W4-F002 | PARTIAL | Evaluation | Corrected 11-task suite has discriminative oracles and a passing non-blind Codex reference run; no blind real-LLM V2 run exists yet. | Freeze V2 and run a fresh real actor baseline plus ablations. |
| W4-F003 | ACCEPTED | Provider/API Egress | Real LLM smoke previously hit `model_overloaded`; current managed sandbox DNS failed and elevated egress was rejected by policy review. | Explicitly approve the concrete provider/base URL before claiming real LLM evidence. |
| W4-F004 | OPEN | Static hygiene | Full-repo ruff has many historical style issues; scoped touched-module ruff passes. | Decide whether to run a separate lint cleanup branch. |
| W4-F005 | ACCEPTED | Type checking | Full mypy still has historical import-chain/stub debt. | Excluded by user for this closeout; keep tracked as type debt. |

## Conclusion

Current four-week status: functional runtime foundations are in good shape. The repository passes full tests, including real Docker boundaries when terminal permissions allow it. The strongest implemented evidence is around Git safety, command policy, sandbox boundaries, durable sessions, CLI contracts, and retrieval evaluation.

The benchmark infrastructure now has a fixed, reproducible medium-repo suite,
a null preflight, and a solvability reference. The biggest remaining product
gap is the actor itself: it is still a one-shot context-to-patch component, so a
fresh blind run measures that limited scaffold rather than a tool-using coding
agent. Real V2 performance and ablations must be rerun after the suite freeze.
