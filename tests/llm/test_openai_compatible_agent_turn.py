from __future__ import annotations

import io
import json
import urllib.error
from typing import Any, Self

import pytest

from codeteam.llm import openai_compatible as adapter
from codeteam.llm.base import (
    InputBudgetExceededError,
    ModelFinishState,
    ModelRequest,
    ModelResponseMode,
)
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _config(**updates: str) -> dict[str, str]:
    return {
        "CODETEAM_LLM_BASE_URL": "https://provider.test/v1",
        "CODETEAM_LLM_API_KEY": "secret",
        "CODETEAM_LLM_MODEL": "test-model",
        **updates,
    }


def _request(messages: tuple[Message, ...] | None = None) -> ModelRequest:
    return ModelRequest(
        messages=messages or (Message(role="user", content="fix it"),),
        tools=(
            {
                "name": "apply_patch",
                "description": "Apply a safe patch.",
                "arguments": {
                    "type": "object",
                    "properties": {"patch": {"type": "string"}},
                    "required": ["patch"],
                },
            },
        ),
        max_input_tokens=8000,
        max_output_tokens=1000,
        model_context_window=10000,
        safety_headroom_tokens=1000,
        native_tools=True,
        reasoning_enabled=False,
    )


def test_native_request_and_turn_preserve_tools_budget_usage_and_evidence(
    monkeypatch,
) -> None:
    payloads: list[dict[str, Any]] = []
    adapter._NATIVE_TOOL_CAPABILITY.clear()
    adapter._PROVIDER_RUNTIME_STATE.clear()

    def fake_urlopen(request, timeout):
        del timeout
        payloads.append(json.loads(request.data))
        return _FakeResponse(
            {
                "id": "resp-1",
                "model": "provider-model",
                "system_fingerprint": "fp-1",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "provider-call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "apply_patch",
                                        "arguments": '{"patch":"diff"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            }
        )

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_urlopen)
    turn = adapter.chat_completion_model_turn(_config(), _request())

    assert turn.text is None
    assert turn.finish_state is ModelFinishState.TOOL_CALLS
    assert turn.finish_reason == "tool_calls"
    assert turn.response_id == "resp-1"
    assert turn.system_fingerprint == "fp-1"
    assert turn.usage.input_tokens == 12
    assert turn.usage.output_tokens == 7
    assert turn.tool_calls[0].provider_call_id == "provider-call-1"
    assert turn.tool_calls[0].call_id is None
    assert payloads[0]["max_tokens"] == 1000
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert payloads[0]["tools"][0]["function"]["name"] == "apply_patch"
    assert payloads[0]["tools"][0]["function"]["parameters"]["required"] == [
        "patch"
    ]
    assert turn.actual_response_mode is ModelResponseMode.NATIVE_TOOLS


def test_native_assistant_and_tool_result_use_provider_id_on_wire() -> None:
    call = ToolCall(
        call_id="step-1-call-1",
        provider_call_id="opaque-provider-id",
        name="apply_patch",
        arguments={"patch": "diff"},
    )
    assistant = adapter._provider_message(
        Message(role="assistant", content=None, tool_calls=[call])
    )
    tool = adapter._provider_message(
        Message(
            role="tool",
            content="applied",
            tool_call_id="step-1-call-1",
            provider_call_id="opaque-provider-id",
        )
    )

    assert assistant["tool_calls"][0]["id"] == "opaque-provider-id"
    assert tool == {
        "role": "tool",
        "tool_call_id": "opaque-provider-id",
        "content": "applied",
    }
    assert "step-1-call-1" not in json.dumps(tool)


def test_length_and_malformed_native_arguments_are_typed_turns(monkeypatch) -> None:
    responses = iter(
        [
            {
                "choices": [
                    {"finish_reason": "length", "message": {"content": "partial"}}
                ]
            },
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-bad",
                                    "function": {
                                        "name": "apply_patch",
                                        "arguments": "{invalid",
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(next(responses)),
    )

    truncated = adapter.chat_completion_model_turn(_config(), _request())
    malformed = adapter.chat_completion_model_turn(_config(), _request())

    assert truncated.finish_state is ModelFinishState.OUTPUT_TRUNCATED
    assert malformed.finish_state is ModelFinishState.INVALID_TOOL_CALL
    assert malformed.tool_calls == ()
    assert "validation failed" in (malformed.incomplete_reason or "")


def test_empty_turn_gets_bounded_provider_retry(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        del request, timeout
        calls["count"] += 1
        return _FakeResponse(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": None}}
                ]
            }
        )

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_urlopen)
    turn = adapter.chat_completion_model_turn(
        _config(CODETEAM_LLM_MAX_ATTEMPTS="2"),
        _request(),
        sleep_func=lambda seconds: None,
    )

    assert calls["count"] == 2
    assert turn.finish_state is ModelFinishState.INCOMPLETE
    assert "empty content" in (turn.incomplete_reason or "")


def test_native_capability_falls_back_to_textual_codec_only_when_unsupported(
    monkeypatch,
) -> None:
    payloads: list[dict[str, Any]] = []
    adapter._NATIVE_TOOL_CAPABILITY.clear()
    adapter._JSON_MODE_CAPABILITY.clear()

    def fake_urlopen(request, timeout):
        del timeout
        payload = json.loads(request.data)
        payloads.append(payload)
        if "tools" in payload:
            raise urllib.error.HTTPError(
                url="https://provider.test",
                code=400,
                msg="unsupported",
                hdrs={},
                fp=io.BytesIO(b"tools function calling is not supported"),
            )
        return _FakeResponse(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "{}"}}
                ]
            }
        )

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_urlopen)
    turn = adapter.chat_completion_model_turn(_config(), _request())

    assert ["tools" in payload for payload in payloads] == [True, False]
    assert payloads[1]["response_format"] == {"type": "json_object"}
    assert turn.actual_response_mode is ModelResponseMode.JSON_OBJECT
    assert turn.text == "{}"


def test_provider_rejects_oversized_input_before_http(monkeypatch) -> None:
    called = {"count": 0}
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        lambda request, timeout: called.__setitem__("count", called["count"] + 1),
    )
    request = ModelRequest(
        messages=(Message(role="user", content="x" * 2000),),
        max_input_tokens=100,
        max_output_tokens=100,
        model_context_window=1000,
        safety_headroom_tokens=100,
        native_tools=False,
    )

    with pytest.raises(InputBudgetExceededError, match="max_input_tokens"):
        adapter.chat_completion_model_turn(_config(), request)

    assert called["count"] == 0


def test_resource_finish_retries_but_content_filter_does_not(monkeypatch) -> None:
    responses = iter(
        [
            {
                "choices": [
                    {
                        "finish_reason": "insufficient_system_resource",
                        "message": {"content": None},
                    }
                ]
            },
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "done"}}
                ]
            },
            {
                "choices": [
                    {
                        "finish_reason": "content_filter",
                        "message": {"content": None},
                    }
                ]
            },
        ]
    )
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        del request, timeout
        calls["count"] += 1
        return _FakeResponse(next(responses))

    monkeypatch.setattr(adapter.urllib.request, "urlopen", fake_urlopen)
    recovered = adapter.chat_completion_model_turn(
        _config(),
        _request(),
        sleep_func=lambda seconds: None,
    )
    filtered = adapter.chat_completion_model_turn(_config(), _request())

    assert recovered.text == "done"
    assert filtered.finish_state is ModelFinishState.CONTENT_FILTERED
    assert calls["count"] == 3
