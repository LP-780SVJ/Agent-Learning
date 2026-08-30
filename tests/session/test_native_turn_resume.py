from __future__ import annotations

import json

from codeteam.agent.runtime import _message_transform, durable_recent_messages
from codeteam.agent.runtime_models import CompactionMode, ModelOutputEvidence
from codeteam.agent_loop import run_agent_loop
from codeteam.llm.base import (
    ModelFinishState,
    ModelRequest,
    ModelTurn,
    estimate_model_request_tokens,
)
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall
from codeteam.session.models import AgentRuntimeState, Session
from codeteam.tools.registry import ToolRegistry

from .conftest import make_session


class CaptureClient:
    def __init__(self) -> None:
        self.request: ModelRequest | None = None

    def turn(self, request: ModelRequest) -> ModelTurn:
        self.request = request
        return ModelTurn(
            text=json.dumps(
                {
                    "status": "failed",
                    "summary": "resume observed",
                    "tests_passed": False,
                    "error": "stop",
                    "user_input_request": None,
                }
            ),
            finish_state=ModelFinishState.STOP,
            model="mock-model",
        )


def _native_history() -> tuple[Message, Message]:
    call = ToolCall(
        call_id="step-4-call-1",
        provider_call_id="provider-resume-1",
        name="read_file",
        arguments={"path": "app.py"},
    )
    return (
        Message(role="assistant", content=None, tool_calls=[call]),
        Message(
            role="tool",
            content="VALUE = 2",
            tool_call_id="step-4-call-1",
            provider_call_id="provider-resume-1",
        ),
    )


def test_session_round_trip_preserves_native_chain_ids_and_budgets(git_repo) -> None:
    assistant, tool = _native_history()
    session = make_session(
        git_repo,
        runtime_state=AgentRuntimeState(
            step_count=4,
            tool_call_count=3,
            recent_messages=(assistant, tool),
            max_output_tokens=2048,
            model_context_window=16000,
            safety_headroom_tokens=512,
            native_tools=True,
            reasoning_enabled=False,
            workspace_version=3,
            workspace_fingerprint="sha256:fingerprint",
            git_diff_checked_version=3,
            verification_history=(
                {
                    "argv": ["python", "-m", "pytest"],
                    "passed": True,
                    "completion_required": True,
                    "workspace_version": 3,
                },
            ),
        ),
    )

    restored = Session.model_validate_json(session.model_dump_json())
    restored_assistant, restored_tool = restored.runtime_state.recent_messages

    assert restored.runtime_state.step_count == 4
    assert restored.runtime_state.tool_call_count == 3
    assert restored.runtime_state.max_output_tokens == 2048
    assert restored.runtime_state.workspace_fingerprint == "sha256:fingerprint"
    assert restored.runtime_state.git_diff_checked_version == 3
    assert restored.runtime_state.verification_history[0]["workspace_version"] == 3
    assert restored_assistant.tool_calls is not None
    assert restored_assistant.tool_calls[0].call_id == "step-4-call-1"
    assert restored_assistant.tool_calls[0].provider_call_id == "provider-resume-1"
    assert restored_tool.role == "tool"
    assert restored_tool.tool_call_id == "step-4-call-1"
    assert restored_tool.provider_call_id == "provider-resume-1"


def test_native_model_output_evidence_supports_null_content() -> None:
    assistant, _ = _native_history()
    evidence = ModelOutputEvidence(
        step=1,
        raw_content=None,
        native_tool_calls=tuple(assistant.tool_calls or ()),
        finish_state=ModelFinishState.TOOL_CALLS,
        finish_reason="tool_calls",
        provider="openai-compatible",
        response_id="resp-1",
        input_tokens=10,
        output_tokens=4,
    )

    restored = ModelOutputEvidence.model_validate_json(evidence.model_dump_json())
    assert restored.raw_content is None
    assert restored.finish_reason == "tool_calls"
    assert restored.native_tool_calls[0].provider_call_id == "provider-resume-1"
    assert restored.native_tool_calls[0].call_id == "step-4-call-1"


def test_resumed_native_chain_builds_legal_next_request() -> None:
    history = list(_native_history())
    client = CaptureClient()

    run_agent_loop(client, ToolRegistry(), history)

    assert client.request is not None
    assistant, tool = client.request.messages[-2:]
    assert assistant.tool_calls is not None
    assert assistant.tool_calls[0].provider_call_id == "provider-resume-1"
    assert tool.role == "tool"
    assert tool.provider_call_id == "provider-resume-1"


def test_compaction_and_durable_tail_keep_native_turn_atomic() -> None:
    assistant, tool = _native_history()
    messages = [
        Message(role="system", content=json.dumps({"role": "coding_agent"})),
        Message(
            role="user",
            content=json.dumps({"task": "fix", "initial_context": {"files": "x" * 5000}}),
        ),
        Message(role="user", content="old" * 1000),
        assistant,
        tool,
    ]

    compacted = _message_transform(CompactionMode.STRUCTURED, 1200)(messages)
    durable = durable_recent_messages(messages, maximum=2)

    for retained in (tuple(compacted), durable):
        native_assistants = [
            item for item in retained if item.role == "assistant" and item.tool_calls
        ]
        native_tools = [
            item
            for item in retained
            if item.role == "tool" and item.provider_call_id is not None
        ]
        assert len(native_assistants) == len(native_tools) == 1
        assert native_assistants[0].tool_calls is not None
        assert (
            native_assistants[0].tool_calls[0].provider_call_id
            == native_tools[0].provider_call_id
            == "provider-resume-1"
        )

    request = ModelRequest(
        messages=tuple(compacted),
        max_input_tokens=1200,
        max_output_tokens=200,
        model_context_window=1600,
        safety_headroom_tokens=200,
    )
    assert estimate_model_request_tokens(request) <= request.max_input_tokens
