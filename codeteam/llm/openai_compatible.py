"""OpenAI-compatible provider adapter.

All wire-specific payload construction, capability negotiation, response
parsing, provider retries, and transport correlation live in this module.  The
Runtime only consumes ``ModelRequest`` and ``ModelTurn``.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codeteam.errors import classify_exception, should_retry
from codeteam.llm.base import (
    ModelFinishState,
    ModelRequest,
    ModelResponse,
    ModelResponseMode,
    ModelTurn,
    ModelUsage,
    validate_model_request_input,
)
from codeteam.schemas.messages import Message
from codeteam.schemas.tool_calls import ToolCall

DEFAULT_LLM_TIMEOUT_SECONDS = 120.0
DEFAULT_LLM_MAX_ATTEMPTS = 4
DEFAULT_LLM_BACKOFF_SECONDS = 1.0
DEFAULT_LLM_TEMPERATURE = 0.0
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_MODEL_CONTEXT_WINDOW = 32768
DEFAULT_SAFETY_HEADROOM_TOKENS = 1024
_RESPONSE_MODES = frozenset({"auto", "json_object", "text"})
_JSON_MODE_CAPABILITY: dict[tuple[str, str], bool] = {}
_NATIVE_TOOL_CAPABILITY: dict[tuple[str, str], bool] = {}
_THINKING_CONTROL_CAPABILITY: dict[tuple[str, str], bool] = {}
_PROVIDER_RUNTIME_STATE: dict[tuple[str, str], dict[str, object]] = {}


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    base_delay_seconds: float = 0.5


@dataclass(frozen=True)
class ProviderAttemptFailure:
    attempt: int
    category: str
    retryable: bool
    message: str
    status_code: int | None = None

    def render(self) -> str:
        status = f" status={self.status_code}" if self.status_code is not None else ""
        retry = "retryable" if self.retryable else "non-retryable"
        return (
            f"attempt {self.attempt}: {self.category}{status} "
            f"({retry}): {self.message}"
        )


class ProviderRequestError(RuntimeError):
    def __init__(self, failures: list[ProviderAttemptFailure]) -> None:
        self.failures = tuple(failures)
        super().__init__(
            "provider request failed: "
            + " | ".join(failure.render() for failure in self.failures)
        )


class OpenAICompatibleClient:
    """Agent-turn client with a legacy ``complete`` compatibility lane."""

    def __init__(
        self,
        model: str,
        request_func: Callable[[list[Message]], str | ModelResponse] | None = None,
        retry_config: RetryConfig | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        *,
        turn_func: Callable[[ModelRequest], ModelTurn] | None = None,
    ) -> None:
        if request_func is None and turn_func is None:
            raise ValueError("request_func or turn_func is required")
        self.model = model
        self.request_func = request_func
        self.turn_func = turn_func
        self.retry_config = retry_config or RetryConfig()
        self.sleep_func = sleep_func

    def turn(self, request: ModelRequest) -> ModelTurn:
        if self.turn_func is not None:
            # Production turn_func owns HTTP/status retries so it can classify
            # provider finish states as well as transport exceptions.
            return self.turn_func(request)
        if self.request_func is None:  # pragma: no cover - constructor invariant
            raise RuntimeError("legacy request function is unavailable")
        response = self._complete_with_retry(list(request.messages))
        if isinstance(response, str):
            return ModelTurn(text=response, model=self.model)
        return ModelTurn(
            text=response.content,
            model=response.model,
            usage=ModelUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            ),
        )

    def complete(self, messages: list[Message]) -> str | ModelResponse:
        """Compatibility for planners, old tests, and historical actors."""

        if self.request_func is not None:
            return self._complete_with_retry(messages)
        request = ModelRequest(
            messages=tuple(messages),
            max_input_tokens=DEFAULT_MODEL_CONTEXT_WINDOW
            - DEFAULT_MAX_OUTPUT_TOKENS
            - DEFAULT_SAFETY_HEADROOM_TOKENS,
            max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            model_context_window=DEFAULT_MODEL_CONTEXT_WINDOW,
            safety_headroom_tokens=DEFAULT_SAFETY_HEADROOM_TOKENS,
            native_tools=False,
        )
        turn = self.turn(request)
        return ModelResponse(
            content=turn.text or "",
            model=turn.model,
            input_tokens=turn.usage.input_tokens,
            output_tokens=turn.usage.output_tokens,
        )

    def _complete_with_retry(
        self,
        messages: list[Message],
    ) -> str | ModelResponse:
        if self.request_func is None:  # pragma: no cover - guarded by callers
            raise RuntimeError("legacy request function is unavailable")
        retry_index = 0
        while True:
            try:
                return self.request_func(messages)
            except Exception as error:
                agent_error = classify_exception(error)
                if not should_retry(agent_error):
                    raise
                if retry_index >= self.retry_config.max_retries:
                    raise
                delay = self.retry_config.base_delay_seconds * (2**retry_index)
                self.sleep_func(delay)
                retry_index += 1


def build_openai_compatible_client(
    config: dict[str, str],
) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        model=config["CODETEAM_LLM_MODEL"],
        turn_func=lambda request: chat_completion_model_turn(config, request),
    )


def resolve_llm_config(
    secrets_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    config = load_local_secrets(secrets_path)
    source = os.environ if environ is None else environ
    config.update(
        {key: value for key, value in source.items() if key.startswith("CODETEAM_LLM_")}
    )
    missing = [
        key
        for key in (
            "CODETEAM_LLM_BASE_URL",
            "CODETEAM_LLM_API_KEY",
            "CODETEAM_LLM_MODEL",
        )
        if not config.get(key)
    ]
    if missing:
        raise SystemExit(
            f"Missing LLM config keys: {', '.join(missing)}. "
            f"Set them in {secrets_path} or environment variables."
        )
    return config


def load_local_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    config: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        config[key.strip()] = value.strip()
    return config


def chat_completion_model_turn(
    config: dict[str, str],
    request: ModelRequest,
    *,
    sleep_func: Callable[[float], None] = time.sleep,
) -> ModelTurn:
    validate_model_request_input(request)
    max_attempts = _positive_int(
        config.get("CODETEAM_LLM_MAX_ATTEMPTS"),
        default=DEFAULT_LLM_MAX_ATTEMPTS,
    )
    timeout_seconds = _positive_float(
        config.get("CODETEAM_LLM_TIMEOUT_SECONDS"),
        default=DEFAULT_LLM_TIMEOUT_SECONDS,
    )
    backoff_seconds = _positive_float(
        config.get("CODETEAM_LLM_BACKOFF_SECONDS"),
        default=DEFAULT_LLM_BACKOFF_SECONDS,
    )
    temperature = (
        request.temperature
        if request.temperature is not None
        else _nonnegative_float(
            config.get("CODETEAM_LLM_TEMPERATURE"),
            default=DEFAULT_LLM_TEMPERATURE,
        )
    )
    capability_key = _provider_capability_key(config)
    native_requested = (
        request.native_tools
        and bool(request.tools)
    )
    native_active = native_requested and _NATIVE_TOOL_CAPABILITY.get(
        capability_key
    ) is not False
    reasoning_control_active = (
        request.reasoning_enabled is not None
        and _THINKING_CONTROL_CAPABILITY.get(capability_key) is not False
    )
    requested_mode = _response_mode(config, request.response_mode)
    fallback_mode = _fallback_response_mode(
        requested_mode,
        capability_key=capability_key,
    )
    actual_mode = (
        ModelResponseMode.NATIVE_TOOLS
        if native_active
        else ModelResponseMode(fallback_mode)
    )
    prior_state = _PROVIDER_RUNTIME_STATE.get(capability_key, {})
    _PROVIDER_RUNTIME_STATE[capability_key] = {
        "response_mode_requested": (
            ModelResponseMode.NATIVE_TOOLS.value
            if native_requested
            else requested_mode
        ),
        "response_mode_actual": actual_mode.value,
        "response_mode_fallback": bool(
            prior_state.get("response_mode_fallback", False)
        ),
        "native_tools_requested": native_requested,
        "native_tools_actual": native_active,
        "temperature": temperature,
        "reasoning_enabled": request.reasoning_enabled,
        "reasoning_control_actual": reasoning_control_active,
        "max_output_tokens": request.max_output_tokens,
        "max_input_tokens": request.max_input_tokens,
    }
    failures: list[ProviderAttemptFailure] = []

    for attempt in range(1, max_attempts + 1):
        try:
            data = _perform_chat_completion_request(
                config,
                request,
                response_mode=actual_mode,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                include_reasoning_control=reasoning_control_active,
            )
        except urllib.error.HTTPError as error:
            body = _read_http_error_body(error)
            if (
                reasoning_control_active
                and error.code == 400
                and _thinking_control_is_unsupported(body)
            ):
                _THINKING_CONTROL_CAPABILITY[capability_key] = False
                reasoning_control_active = False
                _PROVIDER_RUNTIME_STATE[capability_key][
                    "reasoning_control_actual"
                ] = False
                continue
            if native_active and error.code == 400 and _tools_are_unsupported(body):
                _NATIVE_TOOL_CAPABILITY[capability_key] = False
                native_active = False
                actual_mode = ModelResponseMode(fallback_mode)
                _PROVIDER_RUNTIME_STATE[capability_key].update(
                    {
                        "response_mode_actual": actual_mode.value,
                        "response_mode_fallback": True,
                        "native_tools_actual": False,
                    }
                )
                continue
            if (
                actual_mode is ModelResponseMode.JSON_OBJECT
                and error.code == 400
                and _json_mode_is_unsupported(body)
            ):
                _JSON_MODE_CAPABILITY[capability_key] = False
                actual_mode = ModelResponseMode.TEXT
                _PROVIDER_RUNTIME_STATE[capability_key].update(
                    {
                        "response_mode_actual": actual_mode.value,
                        "response_mode_fallback": True,
                    }
                )
                continue
            failure = _classify_provider_failure(
                error,
                attempt=attempt,
                http_body=body,
            )
            failures.append(failure)
            if not failure.retryable or attempt >= max_attempts:
                raise ProviderRequestError(failures) from error
            sleep_func(backoff_seconds * (2 ** (attempt - 1)))
            continue
        except Exception as error:
            failure = _classify_provider_failure(error, attempt=attempt)
            failures.append(failure)
            if not failure.retryable or attempt >= max_attempts:
                raise ProviderRequestError(failures) from error
            sleep_func(backoff_seconds * (2 ** (attempt - 1)))
            continue

        turn = _parse_model_turn(
            data,
            config=config,
            actual_mode=actual_mode,
        )
        if actual_mode is ModelResponseMode.NATIVE_TOOLS:
            _NATIVE_TOOL_CAPABILITY[capability_key] = True
        elif actual_mode is ModelResponseMode.JSON_OBJECT:
            _JSON_MODE_CAPABILITY[capability_key] = True

        if turn.finish_state is ModelFinishState.RESOURCE_EXHAUSTED:
            failures.append(
                ProviderAttemptFailure(
                    attempt=attempt,
                    category="insufficient_system_resource",
                    retryable=True,
                    message=turn.incomplete_reason or "provider resource exhaustion",
                )
            )
            if attempt >= max_attempts:
                raise ProviderRequestError(failures)
            sleep_func(backoff_seconds * (2 ** (attempt - 1)))
            continue
        if turn.finish_state is ModelFinishState.INCOMPLETE and attempt < max_attempts:
            failures.append(
                ProviderAttemptFailure(
                    attempt=attempt,
                    category="empty_provider_turn",
                    retryable=True,
                    message=turn.incomplete_reason or "empty provider turn",
                )
            )
            sleep_func(backoff_seconds * (2 ** (attempt - 1)))
            continue
        return turn

    raise ProviderRequestError(failures)


def _parse_model_turn(
    data: dict[str, Any],
    *,
    config: dict[str, str],
    actual_mode: ModelResponseMode,
) -> ModelTurn:
    try:
        choice = data["choices"][0]
        message = choice["message"]
        finish_reason_value = choice.get("finish_reason")
        finish_reason = (
            str(finish_reason_value) if finish_reason_value is not None else None
        )
        text_value = message.get("content")
        if text_value is not None and not isinstance(text_value, str):
            raise TypeError("message.content must be a string or null")
        text = text_value
        native_calls = message.get("tool_calls") or []
        if not isinstance(native_calls, list):
            raise TypeError("message.tool_calls must be a list")
        usage_data = data.get("usage") or {}
        usage = ModelUsage(
            input_tokens=int(usage_data.get("prompt_tokens") or 0),
            output_tokens=int(usage_data.get("completion_tokens") or 0),
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderRequestError(
            [
                ProviderAttemptFailure(
                    attempt=1,
                    category="invalid_response",
                    retryable=False,
                    message=f"{type(error).__name__}: {error}",
                )
            ]
        ) from error

    common = {
        "text": text,
        "finish_reason": finish_reason,
        "usage": usage,
        "model": str(data.get("model") or config["CODETEAM_LLM_MODEL"]),
        "provider": "openai-compatible",
        "response_id": _optional_string(data.get("id")),
        "actual_response_mode": actual_mode,
        "system_fingerprint": _optional_string(data.get("system_fingerprint")),
    }
    normalized_reason = (finish_reason or "").lower()
    if normalized_reason == "length":
        return ModelTurn(
            **common,
            finish_state=ModelFinishState.OUTPUT_TRUNCATED,
            incomplete_reason="provider output token limit reached",
        )
    if normalized_reason in {"content_filter", "content_filtered"}:
        return ModelTurn(
            **common,
            finish_state=ModelFinishState.CONTENT_FILTERED,
            incomplete_reason="provider content filter stopped the turn",
        )
    if normalized_reason in {
        "insufficient_system_resource",
        "insufficient_system_resources",
    }:
        return ModelTurn(
            **common,
            finish_state=ModelFinishState.RESOURCE_EXHAUSTED,
            incomplete_reason=normalized_reason,
        )

    tool_calls: list[ToolCall] = []
    for index, item in enumerate(native_calls, start=1):
        try:
            function = item["function"]
            provider_call_id = str(item["id"])
            name = str(function["name"])
            raw_arguments = function.get("arguments", "{}")
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
            if not provider_call_id or not name or not isinstance(arguments, dict):
                raise ValueError("native tool id/name/arguments are invalid")
            tool_calls.append(
                ToolCall(
                    name=name,
                    arguments=arguments,
                    provider_call_id=provider_call_id,
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return ModelTurn(
                **common,
                finish_state=ModelFinishState.INVALID_TOOL_CALL,
                incomplete_reason=(
                    f"native tool call {index} validation failed: "
                    f"{type(error).__name__}: {error}"
                ),
            )

    if tool_calls:
        return ModelTurn(
            **common,
            tool_calls=tuple(tool_calls),
            finish_state=ModelFinishState.TOOL_CALLS,
        )
    if text is None or not text.strip():
        return ModelTurn(
            **common,
            finish_state=ModelFinishState.INCOMPLETE,
            incomplete_reason="provider returned empty content and no tool calls",
        )
    return ModelTurn(**common, finish_state=ModelFinishState.STOP)


def _provider_message(message: Message) -> dict[str, object]:
    if message.role == "assistant" and message.tool_calls:
        calls = []
        for call in message.tool_calls:
            if not call.provider_call_id:
                raise ValueError("native assistant tool call lacks provider_call_id")
            calls.append(
                {
                    "id": call.provider_call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
            )
        return {"role": "assistant", "content": message.content, "tool_calls": calls}
    if message.role == "tool" and message.provider_call_id:
        return {
            "role": "tool",
            "tool_call_id": message.provider_call_id,
            "content": message.content or "",
        }
    if message.role == "tool":
        # Compatibility path for a textual action session.
        observation = {
            "tool_observation": {
                "call_id": message.tool_call_id,
                "content": message.content,
            }
        }
        return {
            "role": "user",
            "content": json.dumps(observation, ensure_ascii=False),
        }
    return {"role": message.role, "content": message.content}


def _provider_tool_schema(tool: dict[str, object]) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("arguments", {"type": "object"}),
        },
    }


def _perform_chat_completion_request(
    config: dict[str, str],
    model_request: ModelRequest,
    *,
    response_mode: ModelResponseMode,
    temperature: float,
    timeout_seconds: float,
    include_reasoning_control: bool = True,
) -> dict[str, Any]:
    payload: dict[str, object] = {
        "model": config["CODETEAM_LLM_MODEL"],
        "messages": [_provider_message(message) for message in model_request.messages],
        "temperature": temperature,
        "max_tokens": model_request.max_output_tokens,
    }
    if response_mode is ModelResponseMode.NATIVE_TOOLS:
        payload["tools"] = [_provider_tool_schema(tool) for tool in model_request.tools]
        payload["tool_choice"] = "auto"
    elif response_mode is ModelResponseMode.JSON_OBJECT:
        payload["response_format"] = {"type": "json_object"}
    if include_reasoning_control and model_request.reasoning_enabled is not None:
        payload["thinking"] = {
            "type": "enabled" if model_request.reasoning_enabled else "disabled"
        }
    request = urllib.request.Request(
        f"{config['CODETEAM_LLM_BASE_URL'].rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['CODETEAM_LLM_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read())
    if not isinstance(data, dict):
        raise TypeError("Provider response root must be a JSON object.")
    return data


def legacy_chat_completion_model_response(
    config: dict[str, str],
    messages: list[Message],
    *,
    sleep_func: Callable[[float], None] = time.sleep,
) -> ModelResponse:
    output_tokens = _positive_int(
        config.get("CODETEAM_LLM_MAX_OUTPUT_TOKENS"),
        default=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    context_window = _positive_int(
        config.get("CODETEAM_LLM_CONTEXT_WINDOW"),
        default=DEFAULT_MODEL_CONTEXT_WINDOW,
    )
    headroom = _positive_int(
        config.get("CODETEAM_LLM_SAFETY_HEADROOM_TOKENS"),
        default=DEFAULT_SAFETY_HEADROOM_TOKENS,
    )
    model_request = ModelRequest(
        messages=tuple(messages),
        max_output_tokens=output_tokens,
        max_input_tokens=max(1, context_window - output_tokens - headroom),
        model_context_window=context_window,
        safety_headroom_tokens=headroom,
        native_tools=False,
        reasoning_enabled=_enabled(
            config.get("CODETEAM_LLM_REASONING_ENABLED"),
            default=False,
        ),
    )
    turn = chat_completion_model_turn(config, model_request, sleep_func=sleep_func)
    return ModelResponse(
        content=turn.text or "",
        model=turn.model,
        input_tokens=turn.usage.input_tokens,
        output_tokens=turn.usage.output_tokens,
    )


def legacy_chat_completion_request(
    config: dict[str, str],
    messages: list[Message],
    *,
    sleep_func: Callable[[float], None] = time.sleep,
) -> str:
    return legacy_chat_completion_model_response(
        config,
        messages,
        sleep_func=sleep_func,
    ).content


def _response_mode(
    config: dict[str, str],
    requested: ModelResponseMode = ModelResponseMode.AUTO,
) -> str:
    configured = config.get("CODETEAM_LLM_RESPONSE_MODE")
    mode = (configured or requested.value).strip().lower()
    if mode == ModelResponseMode.NATIVE_TOOLS.value:
        mode = "auto"
    if mode not in _RESPONSE_MODES:
        raise ValueError("CODETEAM_LLM_RESPONSE_MODE must be auto, json_object, or text.")
    return mode


def _fallback_response_mode(
    requested_mode: str,
    *,
    capability_key: tuple[str, str],
) -> str:
    if requested_mode == "auto":
        return (
            "json_object"
            if _JSON_MODE_CAPABILITY.get(capability_key) is not False
            else "text"
        )
    return requested_mode


def provider_manifest(config: dict[str, str]) -> dict[str, object]:
    key = _provider_capability_key(config)
    state = _PROVIDER_RUNTIME_STATE.get(key)
    if state is not None:
        return dict(state)
    return {
        "response_mode_requested": ModelResponseMode.NATIVE_TOOLS.value,
        "response_mode_actual": None,
        "response_mode_fallback": False,
        "native_tools_requested": _enabled(
            config.get("CODETEAM_LLM_NATIVE_TOOLS"),
            default=True,
        ),
        "native_tools_actual": None,
        "temperature": _nonnegative_float(
            config.get("CODETEAM_LLM_TEMPERATURE"),
            default=DEFAULT_LLM_TEMPERATURE,
        ),
        "reasoning_enabled": _enabled(
            config.get("CODETEAM_LLM_REASONING_ENABLED"),
            default=False,
        ),
        "reasoning_control_actual": None,
        "max_output_tokens": _positive_int(
            config.get("CODETEAM_LLM_MAX_OUTPUT_TOKENS"),
            default=DEFAULT_MAX_OUTPUT_TOKENS,
        ),
    }


def _classify_provider_failure(
    error: Exception,
    *,
    attempt: int,
    http_body: str | None = None,
) -> ProviderAttemptFailure:
    if isinstance(error, ProviderRequestError):
        latest = error.failures[-1]
        return ProviderAttemptFailure(
            attempt=attempt,
            category=latest.category,
            retryable=latest.retryable,
            message=latest.message,
            status_code=latest.status_code,
        )
    if isinstance(error, urllib.error.HTTPError):
        body = http_body if http_body is not None else _read_http_error_body(error)
        message = body or str(error)
        if error.code == 429:
            return ProviderAttemptFailure(attempt, "rate_limit", True, message, error.code)
        if error.code in {408, 504}:
            return ProviderAttemptFailure(attempt, "timeout", True, message, error.code)
        if error.code in {500, 502, 503}:
            return ProviderAttemptFailure(attempt, "server", True, message, error.code)
        if error.code in {401, 403}:
            return ProviderAttemptFailure(attempt, "auth", False, message, error.code)
        return ProviderAttemptFailure(
            attempt,
            "invalid_request" if error.code == 400 else "http",
            False,
            message,
            error.code,
        )
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        category = _network_failure_category(reason)
        return ProviderAttemptFailure(
            attempt,
            category,
            category in {"timeout", "ssl_eof", "network"},
            str(reason),
        )
    if isinstance(error, TimeoutError | socket.timeout):
        return ProviderAttemptFailure(attempt, "timeout", True, str(error))
    if isinstance(error, ssl.SSLError):
        category = "ssl_eof" if _looks_like_ssl_eof(error) else "ssl"
        return ProviderAttemptFailure(attempt, category, category == "ssl_eof", str(error))
    if isinstance(error, OSError):
        category = _network_failure_category(error)
        return ProviderAttemptFailure(
            attempt,
            category,
            category in {"timeout", "ssl_eof", "network"},
            str(error),
        )
    return ProviderAttemptFailure(
        attempt,
        "unknown",
        False,
        f"{type(error).__name__}: {error}",
    )


def _network_failure_category(reason: object) -> str:
    if isinstance(reason, TimeoutError | socket.timeout):
        return "timeout"
    if isinstance(reason, ssl.SSLError):
        return "ssl_eof" if _looks_like_ssl_eof(reason) else "ssl"
    text = str(reason).lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "unexpected_eof" in text or "eof occurred" in text:
        return "ssl_eof"
    if any(
        marker in text
        for marker in (
            "nodename nor servname provided",
            "name or service not known",
            "temporary failure in name resolution",
            "getaddrinfo",
        )
    ):
        return "dns"
    return "network"


def _looks_like_ssl_eof(error: BaseException) -> bool:
    text = str(error).lower()
    return "unexpected_eof" in text or "eof occurred" in text


def _read_http_error_body(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read()
    except OSError:
        return str(error)
    if not body:
        return str(error)
    return body.decode("utf-8", errors="replace")[:1000]


def _json_mode_is_unsupported(body: str) -> bool:
    normalized = body.lower()
    mentions_mode = any(
        marker in normalized
        for marker in ("response_format", "response format", "json_object", "json mode")
    )
    unsupported = any(
        marker in normalized
        for marker in ("not support", "unsupported", "unknown", "unrecognized")
    )
    return mentions_mode and unsupported


def _tools_are_unsupported(body: str) -> bool:
    normalized = body.lower()
    mentions_tools = any(
        marker in normalized
        for marker in ("tools", "tool_choice", "function calling", "function_call")
    )
    unsupported = any(
        marker in normalized
        for marker in ("not support", "unsupported", "unknown", "unrecognized")
    )
    return mentions_tools and unsupported


def _thinking_control_is_unsupported(body: str) -> bool:
    normalized = body.lower()
    mentions_thinking = any(
        marker in normalized
        for marker in ("thinking", "reasoning", "unknown parameter")
    )
    unsupported = any(
        marker in normalized
        for marker in ("not support", "unsupported", "unknown", "unrecognized")
    )
    return mentions_thinking and unsupported


def _provider_capability_key(config: dict[str, str]) -> tuple[str, str]:
    return (
        config["CODETEAM_LLM_BASE_URL"].rstrip("/"),
        config["CODETEAM_LLM_MODEL"],
    )


def _positive_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _nonnegative_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None
