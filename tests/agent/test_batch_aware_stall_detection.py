from __future__ import annotations

import json

from pydantic import BaseModel

from codeteam.agent.completion import CompletionGateDecision
from codeteam.agent_loop import run_agent_loop
from codeteam.limits import AgentLoopLimits
from codeteam.llm.base import ModelFinishState, ModelRequest, ModelTurn
from codeteam.schemas.final_output import CompletionStatus
from codeteam.schemas.tool_calls import ToolCall
from codeteam.state import FailureOrigin, StopReason
from codeteam.tools.base import RegisteredTool
from codeteam.tools.registry import ToolRegistry


class _Args(BaseModel):
    path: str


class _NativeModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = turns
        self.requests: list[ModelRequest] = []

    def turn(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        return self.turns.pop(0)


def _calls(*items: tuple[str, str, str]) -> ModelTurn:
    return ModelTurn(
        tool_calls=tuple(
            ToolCall(
                provider_call_id=provider_id,
                name=name,
                arguments={"path": path},
            )
            for provider_id, name, path in items
        ),
        finish_state=ModelFinishState.TOOL_CALLS,
        model="mock-model",
    )


def _failed() -> ModelTurn:
    return ModelTurn(
        text=json.dumps(
            {
                "status": "failed",
                "summary": "deterministic stop",
                "tests_passed": False,
                "error": "deterministic stop",
            }
        ),
        finish_state=ModelFinishState.STOP,
        model="mock-model",
    )


def _registry(invocations: list[tuple[str, str]]) -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("list_files", "read_file", "search_code", "run_tests", "inspect_environment", "apply_patch"):
        registry.register(
            RegisteredTool(
                name=name,
                description=name,
                args_schema=_Args,
                func=lambda args, tool_name=name: _record(
                    invocations, tool_name, _Args.model_validate(args).path
                ),
            )
        )
    return registry


def _record(invocations: list[tuple[str, str]], name: str, path: str) -> str:
    invocations.append((name, path))
    return json.dumps({"name": name, "path": path})


def test_f03_cached_first_call_does_not_drop_later_native_batch_reads() -> None:
    invocations: list[tuple[str, str]] = []
    model = _NativeModel(
        [
            _calls(
                ("seed-list", "list_files", "."),
                ("seed-agents", "read_file", "AGENTS.md"),
            ),
            _calls(("cached-list", "list_files", ".")),
            _calls(
                ("cached-agents", "read_file", "AGENTS.md"),
                ("fresh-a", "read_file", "new_file_a.py"),
                ("fresh-b", "read_file", "new_file_b.py"),
            ),
            _failed(),
        ]
    )

    result = run_agent_loop(
        model,
        _registry(invocations),
        [],
        cacheable_tools=frozenset({"list_files", "read_file"}),
    )

    assert result.status is CompletionStatus.FAILED
    assert ("read_file", "new_file_a.py") in invocations
    assert ("read_file", "new_file_b.py") in invocations
    assert result.declared_tool_calls == 6
    assert result.processed_tool_calls == 6
    assert result.unprocessed_safe_tool_calls == 0
    batch_results = {
        message.provider_call_id: message.tool_call_id
        for message in result.messages
        if message.role == "tool"
        and message.provider_call_id in {"cached-agents", "fresh-a", "fresh-b"}
    }
    assert batch_results == {
        "cached-agents": "step-3-call-1",
        "fresh-a": "step-3-call-2",
        "fresh-b": "step-3-call-3",
    }


def test_multiple_cached_calls_count_as_one_stalled_turn() -> None:
    invocations: list[tuple[str, str]] = []
    paths = ("a.py", "b.py", "c.py")
    model = _NativeModel(
        [
            _calls(*((f"seed-{path}", "read_file", path) for path in paths)),
            _calls(*((f"cached-{path}", "read_file", path) for path in paths)),
            _failed(),
        ]
    )

    result = run_agent_loop(
        model,
        _registry(invocations),
        [],
        cacheable_tools=frozenset({"read_file"}),
    )

    assert result.stop_reason is StopReason.FAILED
    assert result.steps_used == 3
    assert result.processed_tool_calls == 6


def test_two_complete_cached_turns_stop_only_after_all_results() -> None:
    invocations: list[tuple[str, str]] = []
    paths = ("a.py", "b.py", "c.py")
    model = _NativeModel(
        [
            _calls(*((f"seed-{path}", "read_file", path) for path in paths)),
            _calls(*((f"cached-1-{path}", "read_file", path) for path in paths)),
            _calls(*((f"cached-2-{path}", "read_file", path) for path in paths)),
        ]
    )

    result = run_agent_loop(
        model,
        _registry(invocations),
        [],
        cacheable_tools=frozenset({"read_file"}),
    )

    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.failure_origin is FailureOrigin.CACHED_BATCH_STALL
    assert result.declared_tool_calls == 9
    assert result.processed_tool_calls == 9
    assert result.unprocessed_safe_tool_calls == 0
    assert result.batch_premature_stop_count == 0
    assert result.progress_guard_unprocessed_safe_tool_call_count == 0
    assert len([message for message in result.messages if message.role == "tool"]) == 9


def test_repeated_test_skips_but_fresh_read_in_same_batch_executes() -> None:
    invocations: list[tuple[str, str]] = []
    model = _NativeModel(
        [
            _calls(("test-seed", "run_tests", "tests")),
            _calls(
                ("test-repeat", "run_tests", "tests"),
                ("fresh-read", "read_file", "fresh.py"),
            ),
            _failed(),
        ]
    )

    result = run_agent_loop(
        model,
        _registry(invocations),
        [],
        semantic_repeat_tools=frozenset({"run_tests"}),
        cacheable_tools=frozenset({"read_file"}),
    )

    assert invocations.count(("run_tests", "tests")) == 1
    assert ("read_file", "fresh.py") in invocations
    assert result.stop_reason is StopReason.FAILED
    duplicate = next(
        json.loads(message.content or "{}")
        for message in result.messages
        if message.provider_call_id == "test-repeat"
    )
    assert duplicate["duplicate"] is True


def test_repeated_exploration_does_not_block_later_patch() -> None:
    invocations: list[tuple[str, str]] = []
    version = 0

    def execute(args: BaseModel, *, name: str) -> str:
        nonlocal version
        parsed = _Args.model_validate(args)
        invocations.append((name, parsed.path))
        if name == "apply_patch":
            version += 1
        return name

    registry = ToolRegistry()
    for name in ("inspect_environment", "apply_patch"):
        registry.register(
            RegisteredTool(
                name=name,
                description=name,
                args_schema=_Args,
                func=lambda args, tool_name=name: execute(args, name=tool_name),
            )
        )
    model = _NativeModel(
        [
            _calls(("inspect-seed", "inspect_environment", "yaml")),
            _calls(
                ("inspect-repeat", "inspect_environment", "yaml"),
                ("patch-fresh", "apply_patch", "change"),
            ),
            _failed(),
        ]
    )

    result = run_agent_loop(
        model,
        registry,
        [],
        state_version_provider=lambda: version,
    )

    assert invocations.count(("inspect_environment", "yaml")) == 1
    assert ("apply_patch", "change") in invocations
    assert version == 1
    assert result.stop_reason is StopReason.FAILED


def test_two_wholly_repeated_test_turns_retain_loop_guard() -> None:
    invocations: list[tuple[str, str]] = []
    model = _NativeModel(
        [
            _calls(("test-seed", "run_tests", "tests")),
            _calls(("test-repeat-1", "run_tests", "tests")),
            _calls(("test-repeat-2", "run_tests", "tests")),
        ]
    )

    result = run_agent_loop(
        model,
        _registry(invocations),
        [],
        semantic_repeat_tools=frozenset({"run_tests"}),
    )

    assert result.stop_reason is StopReason.REPEATED_ACTION
    assert result.failure_origin is FailureOrigin.REPEATED_ACTION_STALL
    assert result.processed_tool_calls == 3
    assert invocations.count(("run_tests", "tests")) == 1


def test_repeated_destructive_call_rejects_later_batch_work() -> None:
    invocations: list[tuple[str, str]] = []
    model = _NativeModel(
        [
            _calls(("patch-seed", "apply_patch", "same-change")),
            _calls(
                ("patch-repeat", "apply_patch", "same-change"),
                ("must-not-run", "read_file", "later.py"),
            ),
        ]
    )

    result = run_agent_loop(model, _registry(invocations), [])

    assert result.stop_reason is StopReason.REPEATED_ACTION
    assert result.failure_origin is FailureOrigin.REPEATED_DESTRUCTIVE_ACTION
    assert invocations == [("apply_patch", "same-change")]
    assert result.declared_tool_calls == 3
    assert result.processed_tool_calls == 3
    assert result.rejected_tool_calls == 2
    assert result.unprocessed_safe_tool_calls == 2
    assert result.progress_guard_unprocessed_safe_tool_call_count == 0


def test_tool_budget_rejects_remaining_batch_with_correlated_results() -> None:
    invocations: list[tuple[str, str]] = []
    model = _NativeModel(
        [
            _calls(
                ("budget-1", "read_file", "a.py"),
                ("budget-2", "read_file", "b.py"),
                ("budget-3", "read_file", "c.py"),
            )
        ]
    )

    result = run_agent_loop(
        model,
        _registry(invocations),
        [],
        limits=AgentLoopLimits(max_tool_calls=1),
        cacheable_tools=frozenset({"read_file"}),
    )

    assert result.stop_reason is StopReason.MAX_TOOL_CALLS
    assert result.tool_calls_used == 1
    assert result.declared_tool_calls == 3
    assert result.processed_tool_calls == 3
    assert result.rejected_tool_calls == 2
    assert result.unprocessed_safe_tool_calls == 2
    assert result.progress_guard_unprocessed_safe_tool_call_count == 0
    assert len([message for message in result.messages if message.role == "tool"]) == 3


def test_runtime_halt_rejects_remaining_batch_as_safety_not_progress() -> None:
    invocations: list[tuple[str, str]] = []
    halted = False
    registry = ToolRegistry()

    def execute(args: BaseModel) -> str:
        nonlocal halted
        parsed = _Args.model_validate(args)
        invocations.append(("read_file", parsed.path))
        halted = True
        return parsed.path

    registry.register(RegisteredTool("read_file", "read", _Args, execute))
    result = run_agent_loop(
        _NativeModel(
            [
                _calls(
                    ("halt-1", "read_file", "a.py"),
                    ("halt-2", "read_file", "b.py"),
                    ("halt-3", "read_file", "c.py"),
                )
            ]
        ),
        registry,
        [],
        halt_signal_provider=(
            lambda: (StopReason.PAUSED, "sandbox halted") if halted else None
        ),
    )

    assert result.status is CompletionStatus.NEEDS_USER_INPUT
    assert result.processed_tool_calls == 3
    assert result.rejected_tool_calls == 2
    assert result.unprocessed_safe_tool_calls == 2
    assert result.batch_premature_stop_count == 0


def test_no_progress_failure_origins_are_structured() -> None:
    empty_batch = run_agent_loop(
        _NativeModel(
            [ModelTurn(text='{"tool_calls":[]}', finish_state=ModelFinishState.STOP)]
        ),
        ToolRegistry(),
        [],
    )
    empty_turn = run_agent_loop(
        _NativeModel([ModelTurn(text=None, finish_state=ModelFinishState.STOP)]),
        ToolRegistry(),
        [],
    )
    completion_ignored = run_agent_loop(
        _NativeModel(
            [
                _calls(("ready-1", "list_files", ".")),
                _calls(("ready-2", "list_files", ".")),
            ]
        ),
        _registry([]),
        [],
        completion_gate_provider=lambda: CompletionGateDecision(True, 1, ()),
    )

    assert empty_batch.failure_origin is FailureOrigin.EMPTY_TOOL_BATCH
    assert empty_turn.failure_origin is FailureOrigin.EMPTY_MODEL_TURN
    assert (
        completion_ignored.failure_origin
        is FailureOrigin.COMPLETION_GUIDANCE_IGNORED
    )
    assert completion_ignored.processed_tool_calls == 2
