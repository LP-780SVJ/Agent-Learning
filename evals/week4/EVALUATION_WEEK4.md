# Week 4 Day 7 Evaluation Report

Date: 2026-08-22

CodeTeam commit under evaluation: `56490a1cd858479bf0bb7a98635a0aa337e85365`

This report is a four-week closeout evaluation, not a claim that CodeTeam is already a full autonomous coding benchmark runner. The current CLI can inspect, retrieve context, create durable sessions, pause/resume, diff/rollback, enforce command policy, and execute Docker sandbox checks. The production `codeteam run` path still uses a deterministic `MockPlanner` shell, so the 15-task coding benchmark is specified but not executed as a real patch-producing agent.

## Reproducibility

All commands were run with `.venv/bin/python`.

Key configuration:

| Field | Value |
|---|---|
| Python command | `.venv/bin/python` |
| Repo commit | `56490a1cd858479bf0bb7a98635a0aa337e85365` |
| Retrieval Top K | 5 |
| Retrieval methods | `filename,ripgrep,ripgrep_symbol,hybrid` |
| Week2 dataset | `evals/week2/file_retrieval.jsonl` |
| Medium dataset | `evals/medium_repo/file_retrieval.jsonl` |
| Week4 task suite draft | `evals/week4/agent_task_suite_v1.jsonl` |
| Real LLM smoke | attempted twice; blocked by provider overload |
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
```

## Regression Results

| Check | Result | Notes |
|---|---:|---|
| Full pytest, normal sandbox | `1192 passed, 6 skipped` | Docker skipped because default sandbox cannot access Colima socket. |
| Full pytest, elevated terminal | `1198 passed` | Docker integration executed; no skips. |
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

`evals/w4d1_llm_smoke.py` was attempted twice using local `secrets.local.env`.

Both attempts reached the model path and failed with:

```text
model_overloaded: 模型服务暂时繁忙，正在重试。 [max_attempts_exhausted] (来源: URLError)
```

This is recorded as `BLOCKED_BY_PROVIDER`, not as local CodeTeam success evidence. It does show that the smoke script can load configuration and enter the real provider path.

## 15-Task Agent Evaluation Status

The suite draft is stored at `evals/week4/agent_task_suite_v1.jsonl`.

| Split | Count | Purpose |
|---|---:|---|
| Development | 5 | Debug/tune harness, prompts, retrieval, repair. |
| Held-out | 10 | Freeze-before-run evidence. |

| Type | Count |
|---|---:|
| Bug fix | 5 |
| Feature | 4 |
| Refactor | 3 |
| Maintenance | 3 |

Current status: `NOT_RUN`.

Reason: the current `codeteam run` product path does not yet produce real patches from an LLM-backed actor. Running the 15 tasks today would produce misleading numbers. The correct next step is to implement the independent EvalRunner/Grader and a real patch actor, then run this suite with hidden acceptance tests.

## Ablation Status

| Ablation | Status | Current Evidence |
|---|---|---|
| Retrieval methods | RUN | `filename` / `ripgrep` / `ripgrep_symbol` / `hybrid` results above. |
| Docker sandbox boundary | RUN | Elevated full pytest and sandbox integration passed. |
| CLI invalid format / SIGINT resume | RUN | Covered by subprocess tests. |
| Plan-first vs direct execute | SPECIFIED_NOT_RUN | Requires real patch actor and fixed EvalRunner. |
| Repair loop vs single shot | SPECIFIED_NOT_RUN | Requires real patch actor and hidden oracle. |
| Structured compaction vs truncation | SPECIFIED_NOT_RUN | Data model and tests exist; task-level eval runner still missing. |

## Failure Cases

| ID | Status | Component | Observation | Next Action |
|---|---|---|---|---|
| W4-F001 | OPEN | Retrieval | Medium business/cross-module queries often miss indirect gold files. | Improve semantic query expansion, dependency fanout, and config/doc seeding. |
| W4-F002 | OPEN | Evaluation | 15-task coding suite is designed but not executable as a true actor/judge benchmark. | Build EvalRunner, hidden tests, fresh worktree harness, and patch actor. |
| W4-F003 | ACCEPTED | Provider | Real LLM smoke blocked by external `model_overloaded`. | Retry with stable provider/model before claiming real LLM evidence. |
| W4-F004 | OPEN | Static hygiene | Full-repo ruff has many historical style issues; scoped touched-module ruff passes. | Decide whether to run a separate lint cleanup branch. |
| W4-F005 | ACCEPTED | Type checking | Full mypy still has historical import-chain/stub debt. | Excluded by user for this closeout; keep tracked as type debt. |

## Conclusion

Current four-week status: functional runtime foundations are in good shape. The repository passes full tests, including real Docker boundaries when terminal permissions allow it. The strongest implemented evidence is around Git safety, command policy, sandbox boundaries, durable sessions, CLI contracts, and retrieval evaluation.

The biggest remaining product gap is the true coding actor/evaluation loop: CodeTeam does not yet run a real LLM-backed patch-producing agent through 15 hidden-oracle tasks. Day7 therefore closes with a reproducible evaluation baseline and a clear next benchmark design, not with an inflated task success rate.
