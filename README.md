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
| Unified Coding Agent Runtime | Implemented | `codeteam/agent/runtime.py`, scripted-model integration tests |
| Provider action normalization | Implemented | JSON, fenced JSON, DeepSeek DSML, bounded protocol repair |
| Agent EvalRunner / Grader | Implemented V2 | Same Runtime as `run`; hidden oracle remains grader-only |
| 11-task coding development benchmark | Null preflight 0/11; real run pending | `evals/week4/agent_task_suite_v1.jsonl` |

Latest closeout evidence:

```text
normal sandbox:      1271 passed, 6 skipped
Docker integration:  42 passed in prior elevated closeout run
```

`codeteam run` now uses the real provider-neutral `CodingAgentRuntime`. It creates a linked worktree from request-time `HEAD`, builds initial context, normalizes supported provider response dialects into one action protocol, lets the model inspect and search further, applies patches through the safe patch lane, runs visible verification in Docker, supports local repair turns, inspects the final Git state, and keeps the worktree for review. `agent-eval` is a thin batch shell over the same Runtime; hidden acceptance remains outside the Agent in `AgentGrader`.

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
.venv/bin/python -m codeteam.cli.app agent-eval --suite evals/week4/agent_task_suite_v1.jsonl --output evals/week4/agent_runs/null_baseline --actor null --mode baseline
.venv/bin/python -m codeteam.cli.app run "fix the failing auth test" --repo . --context-budget 4096 --max-steps 20 --max-tool-calls 40 --max-repairs 3 --max-protocol-repairs 2
```

Real-model commands read an OpenAI-compatible provider configuration from
`secrets.local.env` or from environment variables. Environment variables take
precedence, and the secret file is ignored by Git.

```text
CODETEAM_LLM_BASE_URL=https://provider.example/v1
CODETEAM_LLM_API_KEY=...
CODETEAM_LLM_MODEL=provider-model-id
CODETEAM_LLM_RESPONSE_MODE=auto
CODETEAM_LLM_TEMPERATURE=0
```

`--provider` and `--model` must be supplied together when overriding the
configured defaults. The currently executable production provider is
`openai-compatible`; the model registry and switching layer remain
provider-neutral extension points.

### `run` contract

- A run creates `codeteam/<task-id>` in a linked worktree from the repository's
  request-time `HEAD`; it never edits, commits, or merges the caller's worktree.
- The model receives an initial context snapshot and can then call
  `list_files`, `read_file`, `search_code`, `apply_patch`, `run_tests`,
  `git_status`, and `git_diff` within the task worktree.
- Exact assistant responses are retained in a separate `model_outputs.jsonl`
  audit stream. Model-visible history contains only canonical JSON. The Agent
  protocol layer accepts bare JSON, a complete Markdown JSON fence, or a
  validated DeepSeek DSML envelope and assigns its own tool-call IDs.
- Invalid action formats receive at most two consecutive schema-only repair
  turns. A valid action resets the streak; lifetime attempts remain separately
  counted and both values survive Session resume.
- OpenAI-compatible calls default to temperature `0` and negotiate JSON object
  mode. `auto` falls back to text only after an explicit unsupported 400 and
  records the actual mode in the evaluation manifest.
- Patch application passes through path validation, checkpoint creation, the
  safe patch lane, and final Git-state inspection.
- Visible verification runs through `CommandPolicy` and Docker. Docker
  unavailability pauses verification instead of silently using the host shell.
- Verification argv and `cwd` are workspace-relative (`tests/auth`, `.`). The
  Runtime canonicalizes legacy `/workspace/...` inputs before policy checks,
  while Docker alone owns the host-worktree to `/workspace` mapping.
- Read-only exploration uses `(tool, canonical arguments, workspace version)`
  caching. One repeat receives cached evidence; a second unchanged repeat stops
  as `NO_PROGRESS`. A patch increments the version and permits a fresh read.
- Semantically equivalent test retries share one action fingerprint. A retry is
  allowed after the workspace version changes, but repeated failed variants in
  an unchanged workspace stop before spending another model/tool cycle.
- `completed` requires a real source diff, every task-specific visible test to
  pass, an inspected final diff, and a passing final safety check. Broad
  regression commands remain runnable but cannot substitute for the task test.
  A model final message alone is not success.
- Sessions are stored under the repository Git common directory at
  `.git/codeteam/sessions`; the task branch and worktree are retained for human
  inspection.
- CLI exit codes are `0` for completed, `1` for runtime failure, `2` for an
  invalid request, and `130` for pause, approval wait, or interruption.

## Architecture

```text
CLI
  -> Request DTO / render
  -> Worktree + durable Session
  -> CodingAgentRuntime
       -> initial Context Engine snapshot
       -> provider response dialect firewall
       -> provider-neutral JSON action loop
       -> list/read/search/apply_patch/run_tests/git_status/git_diff
       -> final diff + visible verification gate
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
├── agent/                         # unified coding runtime, tools, edits, orchestration
│   ├── protocol.py                # JSON/fence/DSML -> canonical action
│   ├── runtime.py                 # model/action/tool/verification execution loop
│   ├── runtime_models.py          # runtime request, status, evidence, result
│   ├── runtime_tools.py           # seven worktree-scoped coding tools
│   ├── verification.py            # visible-command path canonicalization
│   └── editing.py                 # structured file edits -> local unified diff
├── cli/                           # Typer CLI and commands
└── evaluation/                    # retrieval eval + task-level agent eval
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
- One `CodingAgentRuntime` shared by `run` and `agent-eval`.
- `agent-eval` prepares fresh repositories/worktrees and invokes the independent hidden-oracle Grader only after the Runtime stops.

Important limitation: the 11 tasks are now explicitly a `dev` suite, not held-out evidence. The Runtime is a complete simple-task loop, but its real-model reliability still needs the user-run baseline and ablations below. Null preflight proves harness discrimination; the non-blind Codex reference proves task solvability, not model quality.

## Evaluation

Current evaluation artifacts:

- `evals/week2/file_retrieval.jsonl`: small Week2 retrieval regression suite.
- `evals/medium_repo/file_retrieval.jsonl`: more realistic medium fixture benchmark.
- `evals/week4/week2_retrieval/`: fresh Week4 rerun of the Week2 suite.
- `evals/week4/medium_retrieval/`: fresh Week4 rerun of the medium suite.
- `evals/week4/agent_task_suite_v1.jsonl`: corrected 11-task medium-repo benchmark suite.
- `evals/week4/task_seeds/`: hash-pinned per-task fault seeds applied after the common base archive.
- `eval_hidden/week4/`: hidden acceptance oracle for the 11-task suite.
- `evals/week4/agent_runs/`: null preflight, Codex reference, historical LLM, and ablation outputs.
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

11-task coding benchmark V3 status:

```text
fixture:       tests/fixtures/medium_repo only
base commit:   3956afc05d6c1ad2f3efaac9a510133436c0f700
hidden oracle: 11/11 fail on pristine state
public oracle: 11/11 task tests fail on pristine state
null V3:       0/11 success
Codex reference: 11/11 success (non-blind oracle-informed solvability check)
real LLM V2:  first unified Runtime run 0/11 due protocol integration failure
protocol fix: offline replay accepts all 11 first responses; real rerun pending
```

Legacy `LLMPatchGenerator` and `PatchActor` remain only for compatibility tests
and historical artifacts; production CLI and evaluation execution no longer
call them. The current harness has isolated worktrees, hash-pinned public task
tests, separate broad regression, pristine public/hidden oracle checks,
grader-only hidden acceptance, protected public-oracle paths, fixed task budgets, and
safety invariants. A trustworthy score still requires a fresh real-model run,
and provider failures must be reported separately from Agent failures.

All 11 tasks are a development benchmark. Their results measure regression and
engineering progress, not blind held-out generalization.

### Real-model benchmark commands

Run one task first as a provider/runtime smoke test:

```bash
RUN_DIR="evals/week4/agent_runs/real_llm_smoke_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode baseline \
  --task-id B01 \
  --context-budget 4096 \
  --keep-workspaces
```

Then run the complete 11-task baseline:

```bash
RUN_DIR="evals/week4/agent_runs/real_llm_baseline_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode baseline \
  --context-budget 4096 \
  --keep-workspaces
```

Run the four ablations after the baseline is provider-stable:

```bash
RUN_DIR="evals/week4/agent_runs/real_llm_ablations_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode ablations \
  --context-budget 4096 \
  --keep-workspaces
```

The ablation modes are direct execution without planning, single-shot without
repair, no compaction, and naive tail-only compaction. Compare task success,
hidden acceptance, visible verification, safety, provider-blocked count, steps,
tool calls, repair attempts, tokens, cost, and latency. Canonical Runtime
messages, raw model-output JSONL, final diffs, and verification evidence are
written below each ignored run directory for failure analysis.

Also inspect `protocol_repair_attempt_count` and `protocol_failed_count`. A run
that never reaches a tool because of response-dialect mismatch is an integration
failure, not a coding-capability score.

## Testing

Common commands:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/git -q
.venv/bin/python -m pytest tests/execution -q
.venv/bin/python -m pytest tests/sandbox -q -rs
.venv/bin/python -m pytest tests/session -q
.venv/bin/python -m pytest tests/cli -q
.venv/bin/python -m pytest tests/agent/test_coding_runtime.py -q
.venv/bin/python -m pytest tests/agent/test_output_protocol.py tests/test_agent_loop_protocol.py -q
.venv/bin/python -m pytest tests/evaluation/test_agent_eval_runner.py -q
.venv/bin/python -m pytest tests/evaluation/test_week4_public_oracles.py -q
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
- Earlier real LLM runs predate canonical evidence and discriminative public
  tests; the V3 suite needs a fresh B01 smoke and then an 11-task baseline.
- The unified Runtime is implemented, but the real-model 11-task baseline has
  not yet been rerun after the protocol fix; ablations must wait for a stable
  baseline.
- Provider dialect normalization covers formats observed from the configured
  model, not arbitrary future provider syntaxes; new dialects require explicit
  decoders and adversarial tests.
- Docker remains a hard execution dependency for production verification; unavailable Docker pauses instead of falling back to host shell.
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

1. Run one real-model smoke task, then the 11-task dev baseline.
2. Run ablations: plan-first vs direct, repair vs single shot, and structured vs none/naive compaction.
3. Inspect Runtime artifacts and classify provider, retrieval, patch, verification, safety, and budget failures.
4. Ask the reviewer to inspect the unified Runtime changes and the new evaluation evidence.
5. Fix any newly confirmed P0/P1/P2 findings before using the Runtime as the Week5 multi-agent executor.
6. Improve retrieval on medium repo business/cross-module/doc/config misses.
7. Tackle full-project ruff and mypy as separate cleanup/type-hardening branches.
