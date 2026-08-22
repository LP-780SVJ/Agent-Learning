# Agent-Learning / CodeTeam

`Agent-Learning` is a local-first coding agent runtime built as a learning project. It is not just a chat wrapper: it implements the infrastructure a coding agent needs to inspect a repository, build context, plan work, apply patches safely, run commands through policy and sandbox layers, recover from failures, persist sessions, expose a CLI, and evaluate what actually works.

All project commands must use the local virtual environment:

```bash
.venv/bin/python
```

Do not use the system `python3` for tests, CLI commands, or evaluation runs.

## Current Status

The first four weeks are now at a closeout baseline.

| Area | Status | Evidence |
|---|---|---|
| Agent loop and tool protocol | Implemented | Unit tests for loop limits, tool calls, final output, usage, errors |
| Context engine and retrieval | Implemented | Week2 and medium repo retrieval evals |
| Git patch/worktree/checkpoint | Implemented | `tests/git/` |
| Command policy and approval | Implemented | `tests/execution/` |
| Docker sandbox boundary | Implemented | `tests/sandbox/`, real Docker run passed with terminal access |
| Repair and failure recovery | Implemented foundation | `tests/repair/`, `tests/failures/`, `tests/agent/` |
| Durable session and resume | Implemented | `tests/session/` |
| CLI product layer | Implemented | `tests/cli/`, subprocess E2E |
| 15-task coding benchmark | Designed, not run | `evals/week4/agent_task_suite_v1.jsonl` |

Latest closeout evidence:

```text
normal sandbox:      1192 passed, 6 skipped
elevated terminal:   1198 passed
Docker integration:  42 passed
```

The current `codeteam run` command is still a productized shell around deterministic planning. It creates durable sessions and exercises orchestration, but it does not yet run a real LLM-backed patch-producing actor. For that reason the Week4 Day7 15-task task success rate is intentionally not claimed yet.

## Quick Start

Use Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run the full test suite:

```bash
.venv/bin/python -m pytest -q
```

Show CLI help:

```bash
.venv/bin/python -m codeteam.cli.app --help
```

Core CLI commands:

```bash
.venv/bin/python -m codeteam.cli.app inspect-repo . --format json
.venv/bin/python -m codeteam.cli.app context "refresh token error path" --path tests/fixtures/test_repo --top-k 5 --budget 1024 --format json
.venv/bin/python -m codeteam.cli.app eval --dataset evals/week2/file_retrieval.jsonl --repo tests/fixtures/test_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output evals/week2
.venv/bin/python -m codeteam.cli.app run "inspect this repository task" --repo .
```

## Architecture

```text
CLI
  -> Request DTO / render
  -> Application / Service layer
  -> SingleAgentOrchestrator
  -> Domain modules
       Task / Plan / Context / Git / Execution / Sandbox / Session / LLM
  -> Infrastructure
       subprocess / git / ripgrep / Docker / filesystem / provider HTTP
```

Main package map:

```text
codeteam/
├── agent_loop.py                  # Week1 agent loop
├── schemas/                       # Message, ToolCall, ToolResult, final output
├── tools/                         # calculator, file tools, shell tool, registry
├── usage/                         # token counting, pricing, usage tracking
├── repository/                    # git inventory, scanner, file classification
├── parsing/                       # Python AST and tree-sitter parser registry
├── symbols/                       # symbol extraction and SymbolIndex
├── imports/                       # ImportExtractor, resolver, ImportGraph
├── search/                        # query analysis, ripgrep, candidate generation
├── ranking/                       # file ranking, symbol ranking, PageRank
├── repomap/                       # repo map builder, compressor, renderer
├── context/                       # context selection, compression, active context
├── application/                   # inspect-repo, build-context, shared indexes
├── git/                           # patch, diff, worktree, checkpoint, rollback
├── execution/                     # CommandPolicy, approval, runner, safe executor
├── sandbox/                       # Docker command builder and Docker runner
├── task/                          # TaskSpec and TaskState
├── planning/                      # Plan models, MockPlanner, LLMPlanner
├── verification/                  # verification command result models/service
├── repair/                        # repair loop and attempt models
├── failures/                      # typed failure classification and recovery policy
├── session/                       # durable session, store, event log, resume
├── llm/                           # provider-neutral model client pieces
├── agent/                         # repository inspection and orchestrator
├── cli/                           # Typer CLI and commands
└── evaluation/                    # retrieval eval models/metrics/runner
```

Detailed architecture notes are maintained in:

- `learning-plan/代码架构.md`
- `learning-plan/设计决策.md`
- `docs/design_decisions/`

## Week1: Agent Loop

Week1 builds the minimal but reliable runtime loop:

```text
messages
  -> model_client.complete()
  -> parse tool calls or final output
  -> ToolRegistry.execute()
  -> append ToolResult
  -> check limits / repeated action / no-progress
  -> validate final output semantics
  -> AgentLoopResult
```

Key decisions:

- Tool calls are structured objects, not free-form shell strings.
- Final output is schema-checked and semantically validated.
- File tools enforce workspace boundaries and write-before-backup.
- Shell execution uses `argv`, `shell=False`, timeout, env/cwd limits, and output truncation.
- Agent loops stop on step budget, tool budget, repeated actions, and invalid final output.
- Runtime behavior emits structured events and usage records.

## Week2: Code Context Engine

Week2 makes the agent repository-aware.

Pipeline:

```text
RepositoryScanner
  -> ParserRegistry
  -> SymbolIndex
  -> ImportGraph
  -> QueryAnalyzer
  -> CandidateGenerator
  -> FileRanker
  -> RepoMapBuilder
  -> InstructionLoader
  -> ContextSelector / ContextCompressor
  -> ContextBuildReport
```

Capabilities:

- Tracked/untracked file inventory.
- Language and file-role classification.
- Python symbol extraction and import resolution.
- AGENTS.md / `.clinerules` loading.
- Test/lint/typecheck command detection.
- Filename, ripgrep, symbol, import-neighbor, test-pair, config, and instruction candidate signals.
- Shared repository index for `context` and `eval`.
- Manifested retrieval evaluation.

## Week3: Git, Patch, Safety, Sandbox

Week3 adds runtime primitives needed before a coding agent can safely edit and execute.

Core boundaries:

```text
Git        -> version state
Worktree   -> task isolation
Checkpoint -> fast restore
Policy     -> command intent
Approval   -> human-controlled side effects
Sandbox    -> capability restriction
```

Highlights:

- Patch validation rejects absolute paths, `..`, `.git`, symlink escape, binary patches, oversized patches, and too many touched files.
- Failed patch application verifies file hashes and git status to detect partial side effects.
- Git worktrees isolate task changes from the main worktree.
- Checkpoints support rollback and ownership validation.
- CommandPolicy classifies safe, sandboxed, approval-required, and denied commands.
- SafeExecutor prevents denied commands from reaching the runner.
- Docker sandbox uses `--network none`, read-only root filesystem, dropped capabilities, no-new-privileges, pids/memory/cpu limits, and controlled workspace mounts.

## Week4: Single-Agent Product Layer

Week4 connects the runtime into a developer-facing single-agent shell.

Capabilities:

- Task and plan state models.
- Verification and repair loop foundations.
- Typed failure classification and recovery decisions.
- Context compaction with explicit budget checks.
- Model switching metadata and provider attribution.
- Durable session snapshot and append-only event log.
- Pause/reconcile/resume workflow.
- CLI commands: `run`, `resume`, `diff`, `rollback`.
- CLI invalid request handling with clean exit code `2`.
- SIGINT E2E: `run` pauses a session, returns `130`, and `resume` rebuilds runtime in a new process.

Important limitation: `run` is not yet a full autonomous coding task actor. The next engineering step is connecting a real LLM planner/patch actor, hidden-oracle EvalRunner, and repair loop into one end-to-end benchmarkable path.

## Evaluation

Current evaluation artifacts:

- `evals/week2/file_retrieval.jsonl`: small Week2 retrieval regression suite.
- `evals/medium_repo/file_retrieval.jsonl`: more realistic medium fixture benchmark.
- `evals/week4/week2_retrieval/`: fresh Week4 rerun of the Week2 suite.
- `evals/week4/medium_retrieval/`: fresh Week4 rerun of the medium suite.
- `evals/week4/agent_task_suite_v1.jsonl`: 15-task agent benchmark design.
- `evals/week4/EVALUATION_WEEK4.md`: Week4 closeout report.
- `test_log/2026-08-22_week4_day7_evaluation_log.md`: command log and conclusions.

Retrieval results from the closeout run:

| Dataset | Method | Recall@5 | Hit@5 |
|---|---|---:|---:|
| Week2 test repo | filename | 0.472 | 0.593 |
| Week2 test repo | ripgrep | 0.969 | 1.000 |
| Week2 test repo | ripgrep_symbol | 0.969 | 1.000 |
| Week2 test repo | hybrid | 1.000 | 1.000 |
| medium repo | filename | 0.325 | 0.400 |
| medium repo | ripgrep | 0.667 | 0.700 |
| medium repo | ripgrep_symbol | 0.686 | 0.733 |
| medium repo | hybrid | 0.653 | 0.700 |

Interpretation:

- The small Week2 suite is a good smoke/regression suite.
- The medium suite is more honest: it exposes weakness on business-behavior, cross-module, config, and docs queries.
- Current retrieval is strongest when exact symbols or direct text are present.
- Current retrieval is weaker when the prompt describes behavior rather than implementation words.

15-task coding benchmark status:

```text
designed: yes
run:      no
reason:   no real patch-producing actor yet
```

The project intentionally does not claim a task success rate until CodeTeam has an actor/judge evaluation harness with hidden acceptance tests, regression tests, fixed budgets, and safety invariants.

## Testing

Common commands:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/git -q
.venv/bin/python -m pytest tests/execution -q
.venv/bin/python -m pytest tests/sandbox -q -rs
.venv/bin/python -m pytest tests/session -q
.venv/bin/python -m pytest tests/cli -q
```

`pytest.ini` excludes `tests/fixtures/` so fixture repository tests are not collected as project tests.

Docker integration tests require:

- Docker CLI and daemon available.
- Local image `codeteam-sandbox:latest`.
- A host directory visible to Docker.

When running inside a restricted terminal sandbox, Docker tests may skip. In a user terminal with Docker permission they should execute.

## Known Limitations

- Full-project mypy still has historical import-chain/stub/type debt.
- Full-project ruff has historical style/lint findings; touched-module ruff gates pass, but repo-wide cleanup should be a separate maintenance branch.
- The real LLM smoke script reached provider code but was blocked by external `model_overloaded` during closeout.
- The current CLI `run` path does not yet produce patches from a real model.
- The 15-task benchmark suite has metadata but hidden tests and EvalRunner/Grader still need implementation.
- Retrieval evaluation is still mostly Python and local fixtures, not a broad multi-language external benchmark.
- Medium repo results show the context engine still needs better semantic retrieval and cross-module expansion.

## Repository Guide

Important directories:

- `.codex/AGENTS.md`: local Codex/coder rules.
- `prompt/`: reusable coder/tester prompts.
- `learning-plan/`: teaching plans, design decision index, architecture document.
- `docs/design_decisions/`: focused design decision records.
- `test_log/`: day-level validation logs.
- `code_review/`: reviewer reports and prompts.
- `evals/`: datasets, raw eval outputs, evaluation reports.
- `tests/fixtures/`: small and medium repositories used by scanner/retrieval/context tests.

## Next Steps

Recommended order:

1. Run the four-week reviewer prompt in `code_review/four_week_reviewer_prompt.md`.
2. Fix any P0/P1/P2 findings from that review.
3. Build the Day7 EvalRunner/Grader with fresh worktrees and hidden acceptance tests.
4. Connect a real LLM-backed patch actor to `codeteam run`.
5. Run the 15-task suite and ablations: plan-first vs direct, repair vs single shot, structured compaction vs truncation.
6. Improve retrieval on medium repo business/cross-module/doc/config misses.
7. Tackle full-project ruff and mypy as separate cleanup/type-hardening branches.
