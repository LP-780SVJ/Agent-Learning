# Week4 Day7 Four-Week Closeout Evaluation Log

Date: 2026-08-22

Branch: `week4`

Commit evaluated: `56490a1cd858479bf0bb7a98635a0aa337e85365`

## Scope

This log closes the first four weeks by checking current non-mypy blockers, rerunning important tests, executing available benchmark/evaluation paths, and recording the status of the Day7 15-task evaluation design.

Out of scope by user decision:

- Fixing full-project mypy historical debt.
- Running a misleading 15-task coding success rate before CodeTeam has a real patch-producing actor and independent EvalRunner/Grader.

## Commands And Results

```bash
.venv/bin/python -m pytest -q
# 1192 passed, 6 skipped in 18.66s
```

```bash
.venv/bin/python -m pytest tests/cli tests/session tests/sandbox tests/execution tests/git -q
# 314 passed, 6 skipped in 13.25s
```

```bash
.venv/bin/python -m pytest tests/sandbox -q -rs
# elevated terminal: 42 passed in 2.13s
```

```bash
.venv/bin/python -m pytest -q
# elevated terminal: 1198 passed in 22.35s
```

```bash
.venv/bin/python -m codeteam.cli.app eval \
  --dataset evals/week2/file_retrieval.jsonl \
  --repo tests/fixtures/test_repo \
  --methods filename,ripgrep,ripgrep_symbol,hybrid \
  --output evals/week4/week2_retrieval
# completed; artifacts written under evals/week4/week2_retrieval
```

```bash
.venv/bin/python -m codeteam.cli.app eval \
  --dataset evals/medium_repo/file_retrieval.jsonl \
  --repo tests/fixtures/medium_repo \
  --methods filename,ripgrep,ripgrep_symbol,hybrid \
  --output evals/week4/medium_retrieval
# completed; artifacts written under evals/week4/medium_retrieval
```

```bash
.venv/bin/python evals/evaluate_day4.py
# completed; wrote artifacts/search_results.json
```

```bash
.venv/bin/python evals/w4d1_llm_smoke.py
# attempted twice; both failed with provider model_overloaded
```

```bash
.venv/bin/python -m ruff check codeteam tests evals
# failed with 196 historical style/lint findings
```

## Current Bug Status

No current non-mypy P0/P1/P2 runtime blocker was found in the executed tests.

Previously open Day6 issues are now fixed and covered:

- Invalid CLI `--format xml` exits 2 without traceback.
- SIGINT run path pauses the session, returns 130, and resume works in a new process.
- Docker boundary tests pass when the terminal can access the Colima Docker daemon.

Known remaining debt:

- Full-project mypy: historical import-chain/stub/type debt, intentionally excluded.
- Full-project ruff: historical cleanup needed; scoped Week4/Day6 ruff gates pass, but repo-wide ruff does not.
- Real LLM smoke: blocked by external provider overload.

## Retrieval Summary

### Week2 Test Repo

| Method | Recall@5 | Hit@5 | Errors | Empty |
|---|---:|---:|---:|---:|
| filename | 0.472 | 0.593 | 0 | 10 |
| ripgrep | 0.969 | 1.000 | 0 | 0 |
| ripgrep_symbol | 0.969 | 1.000 | 0 | 0 |
| hybrid | 1.000 | 1.000 | 0 | 0 |

### Medium Repo

| Method | Recall@5 | Hit@5 | Errors | Empty |
|---|---:|---:|---:|---:|
| filename | 0.325 | 0.400 | 0 | 6 |
| ripgrep | 0.667 | 0.700 | 0 | 4 |
| ripgrep_symbol | 0.686 | 0.733 | 0 | 4 |
| hybrid | 0.653 | 0.700 | 0 | 4 |

Medium repo failure clusters:

- Business behavior queries that require domain understanding rather than direct token matches.
- Cross-module tasks where seed candidates do not fan out to all gold files.
- Docs/config cases where supporting non-code files are under-ranked.

## 15-Task Evaluation

Added: `evals/week4/agent_task_suite_v1.jsonl`

Status: designed, not run.

Reason: Day7 requires actor/judge separation. The current `codeteam run` path uses `MockPlanner` and does not yet generate real code patches. Running the 15 tasks now would produce false confidence rather than useful evidence.

## Day7 Conclusion

Day7 closeout is partially complete in the right way:

- Functional regression and Docker safety evidence: PASS.
- Retrieval benchmark and ablation: PASS/RUN.
- Real LLM smoke: BLOCKED_BY_PROVIDER.
- 15-task coding benchmark: SPECIFIED_NOT_RUN until a real patch actor and independent EvalRunner/Grader exist.
- Full code review: prompt prepared for reviewer; reviewer must write `code_review/four_week_overall_review.md`.

Recommended next phase:

1. Have reviewer run the four-week code review prompt.
2. Address any P0/P1/P2 findings from that review.
3. Build a real Day7 EvalRunner/Grader and patch actor before claiming task success rate.
4. Treat medium_repo retrieval misses as the next context-engine improvement queue.

## 2026-08-23 Update: Agent Eval Harness Implemented

The previous "15-task coding benchmark: SPECIFIED_NOT_RUN" conclusion is now updated.

New implementation:

- `LLMPatchGenerator` extracts unified diffs from real LLM output.
- `PatchActor` builds context, optionally plans, generates a patch, applies it with `GitWorkspace`, and records patch/tokens/events.
- `AgentEvalRunner` creates an isolated git workspace per task from the configured fixture/base commit.
- `AgentGrader` runs hidden acceptance commands, visible regression commands, budget checks, and changed-file safety checks.
- `codeteam agent-eval` exposes the benchmark runner.
- `eval_hidden/week4/` contains hidden oracle V1 for the 15-task suite.

New commands and results:

```bash
.venv/bin/python -m pytest tests/evaluation/test_agent_eval_runner.py tests/evaluation/test_eval_command.py -q
# 5 passed
```

```bash
.venv/bin/python -m pytest -q
# 1195 passed, 6 skipped in 18.62s
```

```bash
.venv/bin/python -m ruff check \
  codeteam/evaluation/agent_models.py \
  codeteam/evaluation/agent_grader.py \
  codeteam/evaluation/agent_runner.py \
  codeteam/evaluation/patch_actor.py \
  codeteam/cli/agent_eval_command.py \
  codeteam/cli/app.py \
  tests/evaluation/test_agent_eval_runner.py \
  eval_hidden/week4
# All checks passed
```

```bash
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output evals/week4/agent_runs/null_baseline \
  --actor null \
  --mode baseline \
  --keep-workspaces
# 15 tasks, 0 success, 0 provider blocked, 4 acceptance passed, 14 regression passed
```

```bash
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output evals/week4/agent_runs/null_ablations \
  --actor null \
  --mode ablations
# direct_execute / single_shot / no_compaction / naive_compaction all ran
# each mode: 15 tasks, 0 success, 4 acceptance passed, 14 regression passed
```

```bash
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output evals/week4/agent_runs/llm_smoke \
  --actor llm \
  --mode baseline \
  --limit 1
# provider_blocked: URLError DNS failure in managed sandbox
```

An elevated network retry was requested but rejected by runtime approval review because it would send repository task/context data to an external LLM endpoint whose concrete destination had not been explicitly approved in this turn.

Updated Day7 conclusion:

- EvalRunner / Grader / LLMPatchGenerator / PatchActor: IMPLEMENTED V1.
- 15-task benchmark harness: RUN with null actor baseline.
- Ablation harness: RUN with null actor across direct execute, single shot, no compaction, and naive compaction.
- Real LLM benchmark: BLOCKED_BY_APPROVAL/API_EGRESS.
- Valid task-solving success rate: NOT CLAIMED.
