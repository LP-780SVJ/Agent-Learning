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
| Agent loop and tool protocol | Native Agent Turn implemented offline | `ModelRequest → ModelTurn`, native tool calls, textual fallback |
| Context engine and retrieval | Implemented | Week2 and medium repo retrieval evals |
| Git patch/worktree/checkpoint | Implemented | `tests/git/` |
| Command policy and approval | Implemented | `tests/execution/` |
| Docker sandbox boundary | Implemented | `tests/sandbox/`, real Docker run passed with terminal access |
| Repair and failure recovery | Implemented foundation | `tests/repair/`, `tests/failures/`, `tests/agent/` |
| Durable session and resume | Implemented | `tests/session/` |
| CLI product layer | Implemented | `tests/cli/`, subprocess E2E |
| Unified Coding Agent Runtime | Implemented | `codeteam/agent/runtime.py`, scripted-model integration tests |
| Provider action normalization | Native-first + fallback | OpenAI-compatible native tools; JSON, fenced JSON, DSML fallback |
| Agent EvalRunner / Grader | Implemented V2 | Same Runtime as `run`; hidden oracle remains grader-only |
| 11-task coding development benchmark | NOT_RUN after Agent Turn change | Wait for user B01 smoke and Completion Ownership fix |

Latest closeout evidence:

```text
normal sandbox:      1308 passed, 6 skipped
Docker integration:  42 passed in prior elevated closeout run
```

`codeteam run` now uses the real provider-neutral `CodingAgentRuntime`. Its
production model boundary is `ModelRequest → Provider Adapter → ModelTurn` and
prefers native tool calling. The JSON/fenced-JSON/DSML dialect firewall remains
as compatibility fallback. It creates a linked worktree from request-time
`HEAD`, builds initial context, applies patches through the safe patch lane,
runs visible verification in Docker, and keeps the worktree for review.
`agent-eval` remains a thin batch shell over the same Runtime; hidden acceptance
stays outside the Agent in `AgentGrader`.

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

Execution worktrees default to `~/.codeteam/worktrees`, which keeps them
separate from result artifacts and places them under the current user's home
directory for Colima sharing. Override the base directory with
`--worktree-root PATH` or `CODETEAM_WORKTREE_ROOT`; the CLI option wins.

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

Native tools and reasoning control are per-run CLI options; the documented B01
command explicitly uses `--native-tools --no-reasoning`.

`--provider` and `--model` must be supplied together when overriding the
configured defaults. The currently executable production provider is
`openai-compatible`; the model registry and switching layer remain
provider-neutral extension points.

### `run` contract

- A run creates `codeteam/<task-id>` from request-time `HEAD` below
  `~/.codeteam/worktrees/repos/<repo>-<path-hash>/`; it never edits, commits,
  or merges the caller's worktree. Sessions persist the exact worktree path.
- The model receives an input-budgeted initial context snapshot and existing
  ToolRegistry schemas in `ModelRequest`, then can call
  `list_files`, `read_file`, `search_code`, `apply_patch`, `run_tests`,
  `git_status`, and `git_diff` within the task worktree.
- Production prefers provider-native tool calls. Exact text and structured turn
  evidence are retained in `model_outputs.jsonl`; Model-visible history stores
  structured assistant calls and real `role=tool` results. Runtime-owned
  `step-n-call-m` and opaque provider call IDs remain separate and durable.
  Bare JSON, a complete Markdown JSON fence, and validated DeepSeek DSML remain
  accepted only as fallback, and the Runtime still assigns its own call IDs.
- Invalid action formats receive at most two consecutive schema-only repair
  turns. A valid action resets the streak; lifetime attempts remain separately
  counted and both values survive Session resume.
- OpenAI-compatible calls default to temperature `0`, native tools enabled,
  reasoning disabled, and explicit `max_tokens`. An explicit unsupported-tools
  400 falls back to JSON object/text capability negotiation and records the
  actual mode in the evaluation manifest.
- `--context-budget` is the maximum input budget. It must be no greater than
  `--model-context-window - --max-output-tokens -
  --safety-headroom-tokens`; oversized serialized messages plus tool schemas
  fail before HTTP.
- Patch application accepts unified diff, complete-file edits, or compact exact
  replacements. Every representation becomes a local diff and passes through
  path validation, checkpoint creation, the safe patch lane, and final
  Git-state inspection. Failed patch calls are included in `patch_attempts`.
- Visible verification runs through `CommandPolicy` and Docker. Docker
  unavailability pauses verification instead of silently using the host shell.
- Before the first provider call, Runtime starts a hardened read-only probe with
  the real worktree mount. Missing CLI/daemon/image and invisible bind sources
  return `PAUSED + sandbox_unavailable` with zero model tokens or cost. A
  backend failure during verification also pauses immediately.
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
       -> ModelRequest -> Provider Adapter -> ModelTurn
       -> native action loop / textual dialect firewall fallback
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
├── llm/                           # ModelRequest/ModelTurn + provider adapters
├── agent/                         # unified coding runtime, tools, edits, orchestration
│   ├── protocol.py                # fallback JSON/fence/DSML -> canonical action
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
ModelRequest(messages, tools, budgets)
  -> model_client.turn()
  -> native ModelTurn tool calls, or textual fallback parsing
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

Important limitation: the 11 tasks are explicitly a `dev` suite, not held-out
evidence. The native Agent Turn path has offline coverage only. The user must
run B01 first; the 11-task benchmark and native/text ablation remain `NOT_RUN`
until B01 is stable and Completion Ownership is fixed. Null preflight proves
harness discrimination; the non-blind Codex reference proves task solvability,
not model quality.

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
agent-turn fix: offline native action loop passes; B01 NOT_RUN_BY_CODER
11-task benchmark: NOT_RUN
native/text ablation: NOT_RUN
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

### User-run B01 native-tool smoke

The coder does not call a real LLM or read/print/persist the API key. Configure
`CODETEAM_LLM_BASE_URL`, `CODETEAM_LLM_API_KEY`, and `CODETEAM_LLM_MODEL` in the
environment or ignored `secrets.local.env`, then run this personally:

```bash
RUN_DIR="evals/week4/agent_runs/native_tool_b01_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode baseline \
  --task-id B01 \
  --context-budget 8192 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --safety-headroom-tokens 1024 \
  --native-tools \
  --no-reasoning \
  --worktree-root "$HOME/.codeteam/worktrees" \
  --keep-workspaces
```

Inspect these fields after the run:

- `manifest.json`: `provider_runtime.native_tools_requested/actual`,
  `response_mode_actual`, `reasoning_enabled`, `max_output_tokens`, input budget
  and sandbox/worktree roots.
- result/summary: actor status, failure category, steps, tool calls, patch
  attempts, verification, changed files, provider/environment blocking.
- `_artifacts/B01/model_outputs.jsonl`: `finish_state`, `finish_reason`,
  `actual_response_mode`, usage, response ID, native tool calls, and stable
  `provider_call_id ↔ runtime_call_id` mappings.
- `_artifacts/B01/runtime_messages.json`: structured assistant call followed by
  real `role=tool`, then the next model turn; no textual protocol parse failure
  on the native happy path.
- kept worktree: source patch exists and all patch/test side effects came
  through the existing SafeExecutionService evidence.

Do not run the 11-task real benchmark or real native/text ablation yet. Their
status in this revision is `NOT_RUN`; Fake Provider test pass rates are not
benchmark scores.

Future ablation A is native tool calling and B is the existing textual codec,
with task/model/temperature/output budget held constant. Compare transport
success, parse failure, Runtime execution reached, and task completion only
after the baseline is repeatable.

`--output` stores only reports and audit artifacts. Execution repositories live
under the resolved worktree root. `environment_blocked_count` is reported
separately from provider and Agent failures. The independent Grader still runs
trusted post-run commands on the host, but a passing Grader never upgrades a
paused or failed Runtime to success.

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

The Runtime preflight checks all three before spending Provider tokens. For
Colima, keep the worktree root under the current `$HOME` unless the VM has an
explicit additional mount.

When running inside a restricted terminal sandbox, Docker tests may skip. In a user terminal with Docker permission they should execute.

## Known Limitations

- Full-project mypy still has historical import-chain/stub/type debt.
- Full-project ruff has historical style/lint findings; touched-module ruff gates pass, but repo-wide cleanup should be a separate maintenance branch.
- Earlier real LLM runs predate canonical evidence and discriminative public
  tests; the V3 suite needs the user-run native B01 smoke. B01 is
  `NOT_RUN_BY_CODER`; benchmark and ablation are `NOT_RUN`.
- Runtime completion ownership / `READY_TO_FINALIZE` is still pending. The
  Runtime may still report repeated-action failure after objective gates pass;
  this change intentionally did not redesign the completion state machine.
- Native tool calling is implemented for the OpenAI-compatible adapter and
  falls back explicitly when unsupported. New Provider wire protocols still
  require adapters; full reasoning-content continuation is not implemented.
- Input budgeting counts complete serialized UTF-8 request structure and tools,
  but still uses a replaceable approximate counter rather than a
  provider-exact tokenizer.
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

1. User runs only the documented B01 native-tool smoke and returns its manifest,
   result, model-output evidence, runtime messages, and kept worktree evidence.
2. Fix any real Provider adapter issue exposed by B01 without weakening the
   SafeExecution or dual-ID boundaries.
3. Implement the second knife: Runtime completion ownership /
   `READY_TO_FINALIZE`, without conflating it with action transport.
4. Only after two repeatable B01 runs, run the 11-task dev baseline and then the
   controlled native-vs-text transport ablation.
5. Improve retrieval on medium-repo business/cross-module/doc/config misses and
   keep repo-wide lint/type cleanup as separate maintenance work.
