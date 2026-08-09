# AGENTS.md

## Project Goal

This project is a learning-oriented coding agent framework. The main goal is to build the agent loop, structured model outputs, safe tool execution, stop conditions, and validation layers step by step.

## Python Version

Use Python 3.11 for development.

Must use the project virtual environment for commands: `.venv/bin/python`. Do not use the system default `python3`.

Create and activate a virtual environment with:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Install runtime dependencies with:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Install development dependencies with:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

## Test Command

Run all tests with:

```bash
.venv/bin/python -m pytest -q
```

Run focused tests with:

```bash
.venv/bin/python -m pytest tests/test_agent_loop_stop_conditions.py -q
.venv/bin/python -m pytest tests/test_file_tools.py -q
.venv/bin/python -m pytest tests/test_shell_tool.py -q
```

After the Week 3 Git test directory has been created, run it with:

```bash
.venv/bin/python -m pytest tests/git -q
```

`pytest.ini` excludes `tests/fixtures/` from test discovery because those directories are repository fixtures, not part of the project's own test suite.

## Test Isolation

- Tests that mutate Git state must create a fresh repository under pytest's function-scoped `tmp_path` and establish their own baseline commit.
- Do not apply patches, reset, clean, roll back, or delete files in the project root or directly inside `tests/fixtures/test_repo` and `tests/fixtures/medium_repo`.
- When a realistic repository is needed, copy fixture contents into `tmp_path`, then initialize and modify only that copy.
- Configure Git test identity locally in the temporary repository; never modify the user's global Git configuration.
- Use argv lists, `shell=False`, timeouts, and captured output for Git subprocesses.
- Do not use `skip` or `xfail` to hide product defects. Capability-based conditional skips are allowed only for unavailable optional external services, and must be reported.

## Coding Rules

- Use Pydantic for structured schemas.
- Use enums for fixed status values; do not compare final statuses with raw strings.
- Tool errors should return structured `ToolResult` values through `ToolRegistry`.
- Agent completion is valid only after final output semantic validation.
- Production tools must not access files or directories outside their configured workspace. Pytest-owned temporary directories may be used as isolated test workspaces.
- Shell execution must use `shell=False` and `argv` lists.
- Keep tests focused and run the full pytest suite before considering a change complete.

## Architecture

- `codeteam/schemas/`: message, tool call, tool result, and final output models.
- `codeteam/tools/`: registered tools, safe file operations, calculator, and controlled shell execution.
- `codeteam/llm/`: model response abstractions and mock model clients for deterministic tests.
- `codeteam/agent_loop.py`: model-tool loop, stopping behavior, final output handling, event recording, and usage tracking.
- `codeteam/state.py`: loop state, stop reasons, and repeated-action detection.
- `codeteam/limits.py`: step and tool-call budget checks.
- `codeteam/events.py`: structured agent loop event records.
- `codeteam/errors.py`: error classification and retry decisions.
- `codeteam/usage/`: token usage and cost tracking.
- `codeteam/repository/`, `codeteam/parsing/`, `codeteam/symbols/`, and `codeteam/imports/`: repository discovery and structural indexing.
- `codeteam/search/`, `codeteam/ranking/`, `codeteam/repomap/`, and `codeteam/context/`: retrieval, ranking, repository maps, and budgeted context construction.
- `codeteam/instructions/` and `codeteam/commands/`: scoped project instructions, command detection, and risk classification.
- `codeteam/evaluation/`: retrieval evaluation and reproducibility records.
- `codeteam/git/`: Git diff, patch validation, and workspace operations.

## Safety Notes

File and shell tools provide project-level safety checks, but they are not an operating-system sandbox. Keep workspace restrictions, path resolution, timeout handling, and dangerous-command checks in place when extending tools.
