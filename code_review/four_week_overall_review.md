# Four-Week Overall Code & Test Review

Date: 2026-08-23
Repository: `/Users/root/workspace/Agent-Learning`
Branch observed: `week4` (`## week4...origin/week4 [ahead 1]`)
Reviewer mode: read/run/stat/report only. No source, test, doc, or config files were modified. Secret-like files were checked by path/existence only; no secret values were read or printed.

## Executive Summary

Overall conclusion: **READY_WITH_P2_DEBT**.

The Week4 branch has a strong runtime foundation: 1192 local tests pass, the command policy blocks shell/interpreter string execution and destructive git cases, durable session pause/resume has meaningful reconciliation tests, checkpoint rollback is defensive, context budgeting no longer explodes on a tiny budget, and retrieval evals are reproducible with manifests.

The branch is not blocked by P0/P1 code defects in this review, but it should not be presented as a finished autonomous coding agent. The production `codeteam run` path still creates a mock provider/model session and uses `MockPlanner`; the 15-task Week4 coding suite is designed but not implemented/run as a true hidden-oracle patch benchmark. The main readiness debt is P2: full-repo static gates are not green, Docker boundary tests could not run in this environment, and retrieval metrics show likely overfitting/generalization issues.

## Commands Run

```bash
sed -n '1,260p' code_review/four_week_reviewer_prompt.md
pwd
git status --short
rg --files
git status --short --branch
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/sandbox -q -rs
.venv/bin/python -m ruff check codeteam tests evals
.venv/bin/python -m mypy codeteam tests
.venv/bin/python -m codeteam.cli.app --help
.venv/bin/python -m codeteam.cli.app eval --dataset evals/week2/file_retrieval.jsonl --repo tests/fixtures/test_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output /tmp/codeteam-review-week2-eval
.venv/bin/python -m codeteam.cli.app eval --dataset evals/medium_repo/file_retrieval.jsonl --repo tests/fixtures/medium_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output /tmp/codeteam-review-medium-eval
.venv/bin/python -m codeteam.cli.app context "refresh token 异常从 service 层传播到 API 层的完整链路" --path tests/fixtures/test_repo --top-k 5 --budget 128 --format json
.venv/bin/python -c "from pathlib import Path; patterns=['secrets.local.env','.env','.env.local']; print({p: Path(p).exists() for p in patterns})"
rg --files -uu -g '!.git' -g '*secret*' -g '*.env' -g '.env*' -g '*.pem' -g '*.key' -g '*.token'
.venv/bin/python -c "from pathlib import Path; from codeteam.execution.command_policy import CommandPolicy; from codeteam.execution.models import CommandRequest; root=Path.cwd(); policy=CommandPolicy.default(); cases=[('sh-c',('sh','-c','echo hi')),('python-c',('python','-c','print(1)')),('git-push',('git','push')),('pytest',('.venv/bin/python','-m','pytest','tests/execution','-q'))]; print('\n'.join(f'{name}: '+policy.evaluate(CommandRequest(argv=argv,cwd=root,workspace_root=root,task_id='t')).decision.value for name,argv in cases))"
.venv/bin/python -c "from pathlib import Path; tests=list(Path('tests').rglob('test_*.py')); eval_cases={p.as_posix(): sum(1 for line in p.read_text(encoding='utf-8').splitlines() if line.strip()) for p in [Path('evals/week2/file_retrieval.jsonl'), Path('evals/medium_repo/file_retrieval.jsonl'), Path('evals/week4/agent_task_suite_v1.jsonl')]}; print({'test_files': len(tests), 'eval_cases': eval_cases})"
```

Key results:

| Check | Result |
|---|---|
| Worktree before review | clean |
| Branch | `week4`, ahead of `origin/week4` by 1 commit |
| Full pytest | `1192 passed, 6 skipped in 18.27s` |
| Focused sandbox pytest | `36 passed, 6 skipped in 0.52s` |
| Docker integration environment | skipped: Docker socket permission denied at `unix:///Users/sqlee/.colima/default/docker.sock` |
| Ruff | failed: 196 errors, 153 fixable |
| Mypy | failed before checking: duplicate module `src` in two fixture repos |
| CLI help | success; commands include `inspect-repo`, `context`, `eval`, `run`, `resume`, `diff`, `rollback` |
| Context budget smoke | `budget_tokens=128`, `tokens_used=95`, no diagnostics |
| Test/eval scale | 94 test files; 27 Week2 retrieval cases; 30 medium retrieval cases; 15 Week4 agent-task specs |

Retrieval results reproduced in this review:

| Dataset | Method | Recall@5 | Hit@5 | Avg Latency |
|---|---|---:|---:|---:|
| Week2 fixture | filename | 0.472 | 0.593 | 0ms |
| Week2 fixture | ripgrep | 0.969 | 1.000 | 41ms |
| Week2 fixture | ripgrep_symbol | 0.969 | 1.000 | 41ms |
| Week2 fixture | hybrid | 1.000 | 1.000 | 41ms |
| Medium fixture | filename | 0.325 | 0.400 | 0ms |
| Medium fixture | ripgrep | 0.667 | 0.700 | 35ms |
| Medium fixture | ripgrep_symbol | 0.686 | 0.733 | 35ms |
| Medium fixture | hybrid | 0.653 | 0.700 | 35ms |

## Findings by Severity

### P0

None found.

### P1

None found in code paths independently exercised by this review.

### P2

1. **Static quality gates are not release-clean.** Full-repo ruff fails with 196 errors, including import sorting, unused imports, blind exception catches, and subprocess `check` hygiene. Full mypy cannot start because both `tests/fixtures/test_repo/src/__init__.py` and `tests/fixtures/medium_repo/src/__init__.py` map to duplicate module `src`. This means the repository cannot use `ruff check codeteam tests evals` or `mypy codeteam tests` as unconditional CI gates yet.

2. **Retrieval evaluation has overfitting/generalization risk.** `codeteam/search/query_analyzer.py:118-130` contains a static Chinese business-domain expansion table with entries such as `刷新过期令牌`, `库存预占`, `订单导出`, `数据库会话`, `生成代码`, and expansions to exact fixture-like symbols/files (`refresh_access_token`, `release_inventory_holds`, `export_orders_to_csv`, `AGENTS.md`). This helps explain why Week2 hybrid reaches 1.000 Recall@5 while the medium fixture hybrid is worse than `ripgrep_symbol` (`0.653` vs `0.686`). The expansion mechanism may be useful, but the current table is too aligned with the benchmark fixtures to treat Week2 as strong generalization evidence.

3. **The Week4 agent-task benchmark is specified, not actually executed as a patch-producing benchmark.** `evals/week4/agent_task_suite_v1.jsonl` has 15 cases, but every row has `oracle_review_status: designed_not_implemented`. `evals/week4/EVALUATION_WEEK4.md:112-130` also states the suite is `NOT_RUN`. This is honest documentation, but Week5 readiness should keep this as a major P2 product/eval gap.

4. **The production `codeteam run` path is still a mock planner path.** `codeteam/cli/run_command.py:62-96` persists `provider_id="mock"`, `model_id="mock-model"`, and instantiates `MockPlanner`. `SingleAgentOrchestrator.run()` reaches READY after inspection/planning (`codeteam/agent/orchestrator.py:307-326`); the real execute/repair path exists but requires injected `verification_service` and `workspace` (`codeteam/agent/orchestrator.py:703-712`) and is not wired through the CLI run path reviewed here.

5. **Docker sandbox boundary could not be independently executed in this environment.** The test code has good boundary intent (`tests/sandbox/test_docker_runner_integration.py:38-84`, `237-260`), and the repository's Week4 report records an elevated Docker pass, but this reviewer run saw 6 Docker skips due Colima socket permission. Treat Docker containment claims as environment-gated until CI or an approved elevated run executes them.

6. **DockerRunner bypasses CommandPolicy audit/approval and relies on builder invariants.** `codeteam/sandbox/docker_runner.py:22-31` builds Docker argv and sends it directly to `CommandRunner`, not `SafeCommandExecutor`. `DockerCommandBuilder` has important mount/network/capability constraints (`codeteam/sandbox/docker_builder.py:8-40`, `58-68`, `92-125`), but the boundary is split: normal commands go through policy/approval, sandbox commands trust the builder. That is acceptable for a controlled internal runner, but it is a P2 architecture boundary to keep tested and documented.

### P3

1. **Two command execution abstractions now overlap.** `codeteam/tools/shell.py` and `codeteam/execution/*` both implement subprocess safety. The old shell tool has added string-execution and path checks, but long-term ownership should be simplified so one execution policy is authoritative.

2. **Ruff output points to broad hygiene debt.** Many failures are mechanical (`I001`, unused imports), but some are behavior-relevant style (`BLE001`, subprocess `check=False`). Cleaning this in a separate branch would reduce review noise before Week5.

## Test Quality Audit

Strengths:

- Full suite passes: `1192 passed, 6 skipped`.
- Safety policy tests cover destructive git, privilege escalation, shell/interpreter `-c`, credential paths, network and remote-write decisions. See `tests/execution/test_command_policy.py:137-220` and the reviewer smoke result: `sh-c: deny`, `python-c: deny`, `git-push: require_approval`, `pytest: allow_sandboxed`.
- Session pause/resume has useful ordering and reconciliation coverage, including pause ordering, terminal rejection, writer-lock release, repo mismatch, missing base SHA, and drift cases (`tests/session/test_day4_pause_reconcile_resume.py:98-212`).
- Docker integration tests encode real boundaries: workspace read/write, host secret non-readability, network/root/socket checks. They are skip-gated correctly when Docker is unavailable.
- Context budget smoke demonstrates small-budget compression still works at the CLI boundary: `tokens_used=95` for `budget_tokens=128`.

Gaps:

- Docker integration did not run in this environment; the 6 skips are expected but leave security containment unverified by this review run.
- Full static gates are not green, so quality is currently measured mostly by pytest rather than pytest + lint + typecheck.
- The main CLI `run` path is covered as lifecycle/planning, not as real patch application and hidden acceptance testing.

## Evaluation Quality Audit

Good:

- `codeteam/cli/eval_command.py:134-171` writes manifests with dataset hash, head commit, dirty status, command argv, Python version, ripgrep version, parser version, ranking weights, and diagnostics summary.
- Retrieval evals are reproducible and ablated across `filename`, `ripgrep`, `ripgrep_symbol`, and `hybrid`.
- The Week4 report is candid that the 15-task suite is not run as a real actor benchmark.

Weak:

- Week2 retrieval is now closer to a regression smoke than a benchmark: 27 cases and domain expansions are aligned to fixture language.
- Medium retrieval reveals the current hybrid ranker can hurt top-5 recall relative to `ripgrep_symbol`.
- Hidden-oracle agent evaluation is not implemented; the suite is a spec, not an evidence source.

## Test/Eval Overfitting Audit

Risk level: **P2**.

Evidence:

- Exact phrase expansions in production query analysis match the fixture-style Chinese tasks and map to exact implementation symbols/configs.
- Week2 hybrid is perfect, but medium hybrid trails the simpler symbol method.
- The Week4 task suite marks oracles as `designed_not_implemented`, so there is not yet a frozen held-out outcome to counterbalance tuning risk.

Recommendation: move benchmark-tuned phrase expansions behind a configurable synonym layer, add tests proving generic behavior on unseen domain phrases, and freeze a held-out eval before tuning the ranker again.

## Architecture Boundary Audit

Healthy boundaries:

- `SafeCommandExecutor` centralizes policy evaluation, approval requests, approval consumption, and attaches final policy metadata to command results (`codeteam/execution/safe_executor.py:27-78`).
- `CommandRunner` uses `shell=False`, stdin `/dev/null`, output byte limits, timeout termination, and cwd-inside-workspace enforcement (`codeteam/execution/runner.py:39-65`, `86-132`).
- Approval fingerprints include argv, cwd, workspace root, task/agent IDs, and timeout (`codeteam/execution/models.py:57-73`), reducing grant replay ambiguity.
- Checkpointing rejects symlinks and keeps runtime state outside workspace (`codeteam/git/checkpoint.py:46-49`, `100-107`, `331-343`).
- Session reconciliation separates durable state from runtime objects and flags repo/worktree drift before resume.

Boundary debt:

- Docker execution is a parallel path around `SafeCommandExecutor`, with safety in `DockerCommandBuilder` rather than the common policy chain.
- CLI `run` is lifecycle-only and mock-planned; real execution/repair is not wired end-to-end.
- Old shell-tool safety and new execution-policy safety should converge to one authoritative path.

## Redundant Code / Simplification Opportunities

- Consolidate `codeteam/tools/shell.py` and `codeteam/execution/*` so all subprocess execution uses one request/result model, one policy decision model, and one approval/audit path.
- Split benchmark/domain synonym expansion out of `QueryAnalyzer` into config/data with clear provenance and test coverage.
- Add a mypy config/exclude for fixture repos or make fixtures explicit packages, so typecheck can run on first-party code without duplicate-module failure.
- Make ruff cleanup a separate mechanical PR/commit to avoid mixing style churn into Week5 behavior work.

## Security Audit

Positive findings:

- Policy denies shell string execution and interpreter `-c` paths, including `/usr/bin/env python -c` in tests.
- Policy denies destructive git reset/clean/branch-delete and force-push; normal `git push` requires approval.
- Credential-like path arguments are denied by policy; Docker builder also blocks credential-like workspace mount markers.
- Subprocess execution uses `shell=False`; output is byte-limited; timeouts kill process groups.
- Checkpoint snapshots refuse symlink traversal, which protects against leaking outside-workspace files.
- Secret-like file check found `secrets.local.env` present; `.env` and `.env.local` absent. Contents were not read.

Concerns:

- Docker boundary tests skipped in this environment, so host isolation was not independently validated here.
- `CommandRunner` allowlists `HOME` into process env (`codeteam/execution/runner.py:19-26`, `134-139`). That may be necessary for tooling, but it increases the need for sandboxing/policy on commands that can read arbitrary files.
- `DockerRunner` is not policy-mediated, so builder tests become security-critical.

## Known Historical Debt

- Full ruff remains noisy; Week4 report also tracked this as static hygiene debt.
- Full mypy remains blocked by fixture packaging, so type health is not continuously measurable.
- Real LLM smoke was previously provider-blocked in Week4 documentation; this review did not retry provider calls or inspect secret values.
- The autonomous agent benchmark is not yet executable as an honest pass/fail patch benchmark.

## Next-Stage Readiness

Status: **READY_WITH_P2_DEBT**.

The codebase is ready to enter Week5 if Week5 is framed as building the real actor/eval loop on top of a reasonably tested foundation. It is not ready to claim autonomous coding benchmark performance. Before any release-style claim, require:

- Green full pytest plus Docker integration in CI or an approved Docker-capable environment.
- A lint/typecheck policy that is either green or explicitly scoped.
- An implemented EvalRunner/Grader with fresh worktrees, hidden acceptance commands, no main-worktree mutation, and frozen held-out results.
- Retrieval improvements validated on unseen tasks, not only the Week2 fixture.

## Recommended Fix Order

1. Fix mypy fixture duplicate-module blocking, then decide the exact first-party mypy scope.
2. Run/record Docker integration in a Docker-capable CI/elevated environment.
3. Implement the Week4/Week5 EvalRunner + Grader + fresh-worktree harness before tuning agent behavior.
4. Wire a real patch-producing actor into `codeteam run`, keeping mock mode as an explicit test fixture.
5. Move query domain expansions out of hardcoded production logic or freeze them as config with non-fixture tests.
6. Clean ruff in a mechanical branch, starting with import sorting/unused imports and then behavior-relevant lint.
7. Consolidate old shell tool execution with the new command policy/executor path.

Final conclusion: **READY_WITH_P2_DEBT**
