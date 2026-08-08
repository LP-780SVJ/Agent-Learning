# Week 2 Overall Code Review

## Executive Summary

当前仓库可以继续进入下一阶段，但不建议把 Week2 结果视为“上下文引擎已可靠”。主测试套件通过，`inspect-repo`、`context`、`eval` 的主命令可运行，路径格式和 CLI/application 分层整体可用。

最大风险有两个：第一，`context` 在小预算下会报告 `tokens_used > budget_tokens`，这直接违反上下文预算边界；第二，Week1 已指出的 shell/interpreter `-c` 绕过仍然存在，可以在临时 workspace 配置下读取 workspace 外文件。评测方面，当前 20 条数据更像 “ripgrep + 少量 filename” benchmark，不能证明 SymbolIndex 或 ImportGraph 带来增益。

## Verification

| Command | Result |
|---|---|
| `.venv/bin/python --version` | Python 3.11.15 |
| `.venv/bin/python -m pytest -q` | 433 passed in 1.64s |
| `.venv/bin/python -m codeteam.cli.app inspect-repo . --format json` | passed; root `/Users/root/workspace/Agent-Learning`; dirty=true; tracked_files=216; python=176; parse success=176; symbol_count=5408; import edges=292 |
| `.venv/bin/python -m codeteam.cli.app inspect-repo tests/fixtures/test_repo --format json` | passed; dirty=true; tracked_files=16; python=14; parse success=14; symbol_count=1571; import edges=8 |
| `.venv/bin/python -m codeteam.cli.app context "...完整链路" --path tests/fixtures/test_repo --top-k 5 --budget 1024 --format json` | passed; tokens_used=1005, budget_tokens=1024; top files: api, test_auth, service, exceptions, database |
| same context command with `--budget 256` | passed; tokens_used=243, budget_tokens=256 |
| same context command with `--budget 128` | command exits 0 but violates budget: tokens_used=176, budget_tokens=128; `code_context=[]` |
| `.venv/bin/python -m codeteam.cli.app eval --dataset evals/week2/file_retrieval.jsonl --repo tests/fixtures/test_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output /tmp/codeteam-review-eval` | passed; filename Recall@5=0.333 Hit@5=0.350; ripgrep/ripgrep_symbol/hybrid all Recall@5=0.800 Hit@5=0.800 |
| `.venv/bin/python -m codeteam.cli.app eval --dataset evals/week2/file_retrieval.jsonl --repo tests/fixtures/test_repo --methods bogus --output /tmp/codeteam-review-bogus` | correctly failed with exit code 1: unknown method |

Metric recomputation from `/tmp/codeteam-review-eval/*.jsonl`:

| Method | Recall@5 | Hit@5 | Errors | Empty predictions |
|---|---:|---:|---:|---:|
| filename | 0.333 | 0.350 | 0 | 11 |
| ripgrep | 0.800 | 0.800 | 0 | 4 |
| ripgrep_symbol | 0.800 | 0.800 | 0 | 4 |
| hybrid | 0.800 | 0.800 | 0 | 4 |

Shell bypass check used only `.venv/bin/python` plus temporary workspace configuration. `["sh","-c","cat /etc/hosts"]`, `["bash","-c","cat /etc/hosts"]`, and `[sys.executable,"-c","open('/etc/hosts')..."]` all exited 0 and returned `/etc/hosts` content.

## Findings

### [P1] `context` can exceed the requested token budget — codeteam/application/build_context.py:234

Problem: `BuildContext.execute()` subtracts `repo_map_tokens` and instruction summary tokens from `budget_tokens` only to compute `code_budget`. If repo map plus instruction summaries already exceed the total budget, code context is dropped, but `tokens_used` is still returned as `repo_map_tokens + instruction_tokens + tokens_after` without enforcing `<= budget_tokens`.

Why it matters: The context command is the boundary that protects LLM input size. A reported budget that is not actually respected will fail precisely in tight-budget scenarios, where compression is supposed to be most valuable.

Evidence: Required verification command with `--budget 128` returned `tokens_used=176` and `budget_tokens=128`. The code path is visible in `code_budget = max(0, budget_tokens - repo_map_tokens - instruction_tokens)` and final `tokens_used=repo_map_tokens + instruction_tokens + tokens_after` at codeteam/application/build_context.py:236 and codeteam/application/build_context.py:289. `_repo_map_budget()` also enforces a minimum 128-token repo map slice for any positive budget at codeteam/application/build_context.py:324, which is too large once instructions are added.

Recommendation: Treat the final context as one budgeted artifact. Either reserve sub-budgets that sum to the total and enforce each section, or iteratively shrink repo map, instruction summaries, and code context until the total fits. If no useful artifact can fit, return a structured warning instead of an over-budget report.

Test suggestion: Add an integration test around `ContextApplicationService.execute(..., budget_tokens=128)` asserting `report.tokens_used <= report.budget_tokens`, with separate assertions for 128, 256, and 1024.

### [P1] Shell/interpreter string bypass from Week1 still exists — codeteam/tools/shell.py:151

Problem: `_validate_argv()` checks only the top-level executable and path-like argv entries. It does not inspect shell or interpreter `-c` payloads, so paths and dangerous commands hidden inside a command string bypass workspace/path checks.

Why it matters: The tool is advertised as a safe command runner inside the workspace, and `.codex/AGENTS.md` requires tools not access files outside the workspace. This is not a full OS sandbox, but the current implementation gives a false sense of boundary enforcement.

Evidence: I verified that `sh -c cat /etc/hosts`, `bash -c cat /etc/hosts`, and Python `-c open('/etc/hosts')` all pass validation and read workspace-external content. Week1 already documented the same class of issue in code_review/week1_review.md:3.

Recommendation: Block known shell `-c` forms (`sh`, `bash`, `zsh`, etc.) and interpreter string execution (`python -c`, `node -e`, `ruby -e`, etc.) by default, or move to a narrow allowlist of executable + argument shapes. If interpreter execution is needed, require a script path that is validated as inside the workspace.

Test suggestion: Add explicit tests for `sh -c`, `bash -c`, and `python -c` attempting workspace-external reads and direct dangerous operations such as `rm` hidden in a string.

### [P2] Eval retrievers rebuild indexes and full context on every case — codeteam/cli/eval_command.py:246

Problem: `_run_pipeline()` calls `_build_indexes(root)` for every query/method, then calls `scanner.scan()` again, constructs `BuildContext`, builds repo map, loads instructions, detects commands, and compresses context even though eval only needs `TopK` file paths.

Why it matters: This is acceptable for a 16-file fixture, but it will distort latency and scale poorly. It also increases the chance that non-retrieval code affects retrieval evaluation. For example, a context budget bug or instruction loader bug can fail an eval run whose metric is supposed to isolate file retrieval.

Evidence: The repeated indexing starts at codeteam/cli/eval_command.py:246, re-scan happens at codeteam/cli/eval_command.py:254, and full context construction happens at codeteam/cli/eval_command.py:274. `_build_indexes()` always builds SymbolIndex and ImportGraph even for `filename` and `ripgrep` methods.

Recommendation: Build repository indexes once per method or once per eval run, then route each method through a pure retrieval function that returns ranked paths. Keep repo map/context compression out of retrieval metrics unless the metric explicitly evaluates full context building.

Test suggestion: Add a test with a spy/fake scanner asserting one index build per method, not per case. Add a second test that retrieval eval can run without invoking repo map or code-context compression.

### [P2] Context/eval indexing silently swallows extraction failures — codeteam/application/build_context.py:446

Problem: `build_repository_context_indexes()` catches all exceptions and continues without diagnostics. `_build_indexes()` inside eval does the same with `except Exception: pass`.

Why it matters: `inspect-repo` correctly records warnings for parse/read/extract failures, but `context` and `eval` can silently lose symbols/imports and produce lower recall with no evidence. This makes failure analysis and benchmark trust much weaker.

Evidence: Silent catch in context indexing is at codeteam/application/build_context.py:430-447. Silent catch in eval indexing is at codeteam/cli/eval_command.py:195-210.

Recommendation: Extract a shared repository index builder that returns indexes plus diagnostics. Surface diagnostics in `context` JSON and eval result manifests, at least as counts and first N warnings.

Test suggestion: Create a temporary repo with one Python file that raises during parsing/extraction or is unreadable; assert `context` and `eval` report a diagnostic while continuing.

### [P2] AGENTS.md explicit commands are not actually parsed — codeteam/commands/detector.py:65

Problem: `CommandDetector.detect()` documents AGENTS.md as the highest-priority command source, but the branch is currently a `pass`. The context command therefore reports commands inferred from pytest config / pyproject, not the explicit commands written in AGENTS.md.

Why it matters: Project instruction files are supposed to tell the agent what to run. In the fixture, AGENTS.md says `uv run pytest tests/ -q`, `uv run ruff check src tests`, and `uv run mypy src`, but the context output reported plain `pytest`, `ruff check .`, and `mypy src` from pyproject.

Evidence: Stub branch at codeteam/commands/detector.py:65-69. Fixture instruction commands are at tests/fixtures/test_repo/AGENTS.md:17-21.

Recommendation: Parse fenced and inline command mentions from effective instruction sources, classify risk, preserve source path/line if possible, and let higher-priority explicit commands override lower-confidence inferred commands only when kind/scope match.

Test suggestion: Add an integration test where AGENTS.md and pyproject disagree; assert the explicit AGENTS command is present and source-traceable.

### [P2] Week2 eval dataset has low discriminative power for SymbolIndex and ImportGraph — evals/week2/file_retrieval.jsonl:1

Problem: Many queries contain exact symbol names, exact error strings, or directly searchable English words. This makes ripgrep strong enough that `ripgrep`, `ripgrep_symbol`, and `hybrid` tie exactly at 0.800 Recall@5 / 0.800 Hit@5.

Why it matters: The report can fairly say "ripgrep is the biggest contributor", but it cannot prove SymbolIndex or ImportGraph is useful. The current dataset under-tests queries where text search cannot directly match the gold file but symbol definitions, references, or import neighbors should help.

Evidence: Exact symbol and error-message rows dominate evals/week2/file_retrieval.jsonl:1-8. Current report also acknowledges zero delta from ripgrep to Symbol and Hybrid at evals/week2/EVALUATION_WEEK2.md:74-80.

Recommendation: Add cases where the query mentions a caller/callee relationship, a re-export, a class method without exact source text, or a dependency chain where a seed candidate must expand to a non-text-matching gold file. Increase fixture size so Top5 is meaningfully competitive.

Test suggestion: Add evaluation regression cases where `ripgrep` misses at least one required file and `hybrid` should recover it through ImportGraph. Track per-case candidate recall, not only final Top5.

### [P2] Chinese natural-language and non-Python instruction recall are known weak spots — codeteam/search/query_analyzer.py:270

Problem: QueryAnalyzer keeps raw CJK spans as low-priority terms but does not map Chinese business language to English code identifiers. CandidateGenerator also restricts ripgrep searches to Python files, so AGENTS.md / config content is easy to miss unless special config trigger terms fire.

Why it matters: The actual target use case includes Chinese natural-language tasks. Four hybrid predictions are empty, including business behavior and instruction-rule queries. This is the main user-facing recall gap.

Evidence: Chinese span extraction is raw at codeteam/search/query_analyzer.py:270-290. Ripgrep candidate search uses `file_types=["py"]` at codeteam/search/candidate_generator.py:313-345. The report lists failures for Chinese business queries and AGENTS.md recall at evals/week2/EVALUATION_WEEK2.md:91-151.

Recommendation: Add a deterministic bilingual/domain expansion layer for key business terms, plus a separate instruction/config text index that searches Markdown/TOML when query terms imply rules, tests, generated code, or configuration.

Test suggestion: Add regression tests for "刷新过期令牌" -> `refresh_access_token`, "库存预占" -> `release_inventory_holds`, and "生成代码目录不允许手动修改" -> `AGENTS.md`.

### [P2] Manifests record key fields but not enough to reproduce dirty runs — codeteam/cli/eval_command.py:110

Problem: Eval manifests include repo path, commit, dirty boolean, dataset hash, method, top_k, ranking weights, and timestamp. They do not include dirty file lists/diffs, Python and ripgrep versions, candidate limit, context budget, parser versions, or exact command argv.

Why it matters: Both the main repo and fixture repo currently report dirty=true. With only a boolean, a future reader cannot reconstruct what code/data state produced the metrics.

Evidence: Manifest fields are defined at codeteam/cli/eval_command.py:110-119. The generated manifests correctly show `dirty: true`, but no dirty file details.

Recommendation: Keep the current fields, but add dirty path summaries, dataset path, eval command argv, Python version, ripgrep version, parser/tree-sitter versions, candidate_limit, budget, and optionally a hash of relevant fixture files.

Test suggestion: Unit-test `save_run_manifest()` with a fake git wrapper or temporary git repo and assert required reproducibility fields are present.

### [P3] README and command docs are stale after Week2 — README.md:78

Problem: README still says the project has no independent CLI and lists unittest as the main runner, while Week2 adds `codeteam.cli.app`, `pytest.ini`, and eval/context commands.

Why it matters: The virtualenv and requirements issue from Week1 is mostly fixed, but stale docs can still send contributors to the wrong verification flow.

Evidence: README.md:78-97 says no CLI and documents `.venv/bin/python -m unittest discover tests`; current verification uses `.venv/bin/python -m pytest -q` and CLI commands.

Recommendation: Update README to document `inspect-repo`, `context`, `eval`, `.venv/bin/python -m pytest -q`, and the Week2 fixture/eval workflow.

Test suggestion: None beyond doc review; optionally add a lightweight smoke test in CI docs that runs `--help`.

## Evaluation Audit

The published Week2 metric table is accurate for the checked outputs. My recomputation matches `EVALUATION_WEEK2.md`: filename is 0.333/0.350 and the other three methods are 0.800/0.800. Unknown eval method correctly fails.

Objectivity: The dataset includes rationales and category labels, which is good. However, the dataset creator and system developer are likely the same person, the fixture is tiny, and several gold labels are close to exact query strings or fixture names. This limits objectivity.

Completeness: The five categories are a good start, but the dataset does not sufficiently cover non-Python docs/config recall, Chinese-to-English mapping, cross-module recall without text seeds, parser failure diagnostics, or ImportGraph-only gains.

Fairness: The intended ablation table is clear, but implementation rebuilds all indexes and full context for each query/method. That makes latency less meaningful and allows context-related bugs to influence retrieval evaluation.

Current result interpretation: SymbolIndex and ImportGraph bring no observed gain because ripgrep already captures most exact English symbols, error messages, and config strings in this small fixture. This is primarily an evaluation-set limitation, not enough evidence of a system defect. That said, ImportGraph also depends on initial seed candidates; when Chinese queries produce no seed, the graph cannot help.

Data leakage / overfitting risk: Some eval queries are reasonable because developers do ask for exact symbol names, but rows like exact symbol and exact error messages strongly favor text search. The fixture also appears built around the query set: auth/order/database/generated examples map cleanly to the five categories. This is useful for smoke tests, but not a robust benchmark.

Manifest audit: Manifests now satisfy the basic requirement of dirty status, dataset hash, commit, and weights. They are not yet sufficient to reproduce dirty worktree runs.

## Test Audit

Reliable coverage:

- Week1 core agent loop tests cover stop conditions, repeated tool calls, final output semantics, events, file tools, pricing, and usage.
- Repository/parsing/import/symbol/search/ranking/repomap unit tests are fairly focused and deterministic.
- `pytest.ini` correctly uses `norecursedirs = tests/fixtures`, so `tests/fixtures/test_repo` is not accidentally run as the main project test suite.

Weak or missing coverage:

- No integration test asserts final `context.tokens_used <= context.budget_tokens`; compressor tests only cover code items, not repo_map + instructions + code combined.
- Eval code has little/no direct unit coverage for unknown methods, retrieval exceptions, manifest fields, dirty state, empty predictions, and method isolation.
- Shell bypass tests requested in Week1 are still missing.
- ImportGraph tests verify graph data structure behavior, but not actual retrieval gain.
- CandidateGenerator import-neighbor test is weak: it passes if any import source appears, rather than proving the expected cross-module gold file is recovered.
- QueryAnalyzer Chinese tests verify extraction does not crash, not semantic mapping to English identifiers.
- Non-Python instruction/config recall is not covered as a first-class retrieval behavior.

Fixture audit: `tests/fixtures/test_repo` is useful as a learning fixture, but it is very small and intentionally shaped around Week2 categories. It should remain a smoke/eval fixture, not be treated as evidence of broad retrieval quality.

## Week 1 Follow-up

- Week1 `[P2] Block shell/interpreter string bypasses` is still present. I reproduced it again with `sh -c`, `bash -c`, and Python `-c`. No regression tests cover it yet.
- Week1 `[P2] Declare Pydantic v2 or use version-compatible APIs` is mostly fixed: `requirements.txt` pins `pydantic==2.13.4`, and `requirements-dev.txt` includes it. The user instruction and `.codex/AGENTS.md` also require `.venv/bin/python`. Remaining cleanup: README still contains stale setup/test text.
- Week1 test gap for reproducible command metadata is partially addressed by requirements files and pytest.ini. It should be finished by updating README and documenting the CLI/eval workflow.

## Recommended Fix Plan

1. Fix `context` total budget enforcement first. Add failing integration tests for 128/256/1024 budgets before changing logic.
2. Fix shell/interpreter `-c` bypass and add explicit regression tests.
3. Extract a shared repository index builder that returns diagnostics; use it from inspect/context/eval.
4. Refactor eval to build indexes once and evaluate pure retrieval outputs, then strengthen manifest fields.
5. Implement AGENTS.md explicit command extraction and source-traceable command priority.
6. Add Chinese/domain query expansion and non-Python instruction/config indexing.
7. Expand Week2 eval with cases that distinguish SymbolIndex and ImportGraph from ripgrep.
8. Update README to reflect pytest, CLI commands, requirements, and eval workflow.

## Appendix

Category recomputation from `/tmp/codeteam-review-eval`:

| Method | exact_symbol | error_message | business_behavior | config_test | cross_module |
|---|---:|---:|---:|---:|---:|
| filename Recall@5 | 0.500 | 0.000 | 0.250 | 0.500 | 0.417 |
| ripgrep Recall@5 | 1.000 | 1.000 | 0.500 | 0.750 | 0.750 |
| ripgrep_symbol Recall@5 | 1.000 | 1.000 | 0.500 | 0.750 | 0.750 |
| hybrid Recall@5 | 1.000 | 1.000 | 0.500 | 0.750 | 0.750 |

Dirty worktree at review start included modified files under `.codex/AGENTS.md`, `codeteam/application/`, `codeteam/cli/`, `codeteam/commands/`, `codeteam/context/`, `codeteam/imports/`, `codeteam/instructions/`, `codeteam/parsing/`, `codeteam/repository/`, `codeteam/search/`, `codeteam/usage/`, and `tests/fixtures/test_repo/`, plus new `codeteam/evaluation/`, `evals/week2/`, and `pytest.ini`. This is expected for Week2 work, but it means eval results should be interpreted as dirty-worktree results.
