# AGENTS.md

## Project Goal

This project is a learning-oriented coding agent framework. The main goal is to build the agent loop, structured model outputs, safe tool execution, stop conditions, and validation layers step by step.

## Python Version

Use Python 3.11 for development.

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
.venv/bin/python -m unittest discover tests
```

Run focused tests with:

```bash
.venv/bin/python -m unittest tests/test_agent_loop_stop_conditions.py
.venv/bin/python -m unittest tests/test_file_tools.py
.venv/bin/python -m unittest tests/test_shell_tool.py
```

## Coding Rules

- Use Pydantic for structured schemas.
- Use enums for fixed status values; do not compare final statuses with raw strings.
- Tool errors should return structured `ToolResult` values through `ToolRegistry`.
- Agent completion is valid only after final output semantic validation.
- Tools must not access files or directories outside the workspace.
- Shell execution must use `shell=False` and `argv` lists.
- Keep tests focused and run the full unittest suite before considering a change complete.

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

## Safety Notes

File and shell tools provide project-level safety checks, but they are not an operating-system sandbox. Keep workspace restrictions, path resolution, timeout handling, and dangerous-command checks in place when extending tools.
