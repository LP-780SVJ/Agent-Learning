"""CLI command for task-level agent coding evaluation."""
from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import AgentEvalSplit, EvalRunConfig, EvalRunMode
from codeteam.evaluation.agent_runner import (
    AgentEvalRunner,
    filter_agent_eval_tasks,
    load_agent_eval_tasks,
    make_run_id,
    summarize_agent_eval_results,
)
from codeteam.llm.base import ModelClient, ModelResponse
from codeteam.llm.openai_compatible import OpenAICompatibleClient
from codeteam.schemas.messages import Message

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_PATH = PROJECT_ROOT / "secrets.local.env"
DEFAULT_LLM_TIMEOUT_SECONDS = 120.0
DEFAULT_LLM_MAX_ATTEMPTS = 4
DEFAULT_LLM_BACKOFF_SECONDS = 1.0


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
        return f"attempt {self.attempt}: {self.category}{status} ({retry}): {self.message}"


class ProviderRequestError(RuntimeError):
    """Raised after a provider request exhausts retries or fails permanently."""

    def __init__(self, failures: list[ProviderAttemptFailure]) -> None:
        self.failures = tuple(failures)
        super().__init__(
            "provider request failed: "
            + " | ".join(failure.render() for failure in self.failures)
        )


class _NullModelClient:
    def complete(self, messages: list[Message]) -> str:
        del messages
        return json.dumps(
            {
                "status": "failed",
                "summary": "Null runtime intentionally performs no work.",
                "tests_passed": False,
                "error": "null_actor",
            }
        )


def make_runtime_model_client(config: dict[str, str]) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        model=config["CODETEAM_LLM_MODEL"],
        request_func=lambda messages: _chat_completion_model_response(
            config,
            messages,
        ),
    )


def run_agent_eval(args: Namespace) -> None:
    tasks = load_agent_eval_tasks(Path(args.suite))
    split = AgentEvalSplit(args.split) if args.split else None
    task_ids = set(args.task_id or []) or None
    selected = filter_agent_eval_tasks(
        tasks,
        split=split,
        task_ids=task_ids,
        limit=args.limit,
    )
    if not selected:
        raise SystemExit("No tasks selected.")

    provider_id = "openai-compatible"
    model_id = "null"
    model_client: ModelClient
    if args.actor == "llm":
        llm_config = _resolve_llm_config()
        provider_id = "openai-compatible"
        model_id = llm_config["CODETEAM_LLM_MODEL"]
        model_client = make_runtime_model_client(llm_config)
    elif args.actor == "null":
        model_client = _NullModelClient()
    else:
        raise SystemExit(f"Unknown actor: {args.actor}")

    runtime = CodingAgentRuntime(model_client=model_client)
    grader = AgentGrader(project_root=PROJECT_ROOT)
    runner = AgentEvalRunner(
        project_root=PROJECT_ROOT,
        runtime=runtime,
        grader=grader,
        keep_workspaces=args.keep_workspaces,
    )

    configs = _build_run_configs(
        mode=args.mode,
        provider_id=provider_id,
        model_id=model_id,
        context_budget=args.context_budget,
    )
    output_root = Path(args.output)
    output_root.mkdir(parents=True, exist_ok=True)
    all_results = []
    for config in configs:
        output_dir = output_root if len(configs) == 1 else output_root / config.mode.value
        results = runner.run_suite(
            tasks=selected,
            config=config,
            output_dir=output_dir,
        )
        all_results.extend(results)
        summary = summarize_agent_eval_results(
            results,
            run_id=config.run_id,
            mode=config.mode,
        )
        print(
            json.dumps(
                summary.model_dump(mode="json"),
                ensure_ascii=False,
            )
        )

    combined = {
        "runs": len(configs),
        "tasks_per_run": len(selected),
        "total_task_results": len(all_results),
        "success_count": sum(result.success for result in all_results),
        "provider_blocked_count": sum(
            result.failure_category == "provider_blocked"
            for result in all_results
        ),
        "protocol_repair_attempt_count": sum(
            result.protocol_repair_attempts for result in all_results
        ),
        "protocol_failed_count": sum(
            result.failure_category == "invalid_final_output"
            for result in all_results
        ),
    }
    (output_root / "combined_summary.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_run_configs(
    *,
    mode: str,
    provider_id: str,
    model_id: str,
    context_budget: int,
) -> list[EvalRunConfig]:
    if mode == "baseline":
        modes = [EvalRunMode.BASELINE]
    elif mode == "ablations":
        modes = [
            EvalRunMode.DIRECT_EXECUTE,
            EvalRunMode.SINGLE_SHOT,
            EvalRunMode.NO_COMPACTION,
            EvalRunMode.NAIVE_COMPACTION,
        ]
    elif mode == "all":
        modes = [
            EvalRunMode.BASELINE,
            EvalRunMode.DIRECT_EXECUTE,
            EvalRunMode.SINGLE_SHOT,
            EvalRunMode.NO_COMPACTION,
            EvalRunMode.NAIVE_COMPACTION,
        ]
    else:
        raise SystemExit(f"Unknown mode: {mode}")

    return [
        _config_for_mode(
            run_mode,
            provider_id=provider_id,
            model_id=model_id,
            context_budget=context_budget,
        )
        for run_mode in modes
    ]


def _config_for_mode(
    mode: EvalRunMode,
    *,
    provider_id: str,
    model_id: str,
    context_budget: int,
) -> EvalRunConfig:
    planning_enabled = mode != EvalRunMode.DIRECT_EXECUTE
    repair_enabled = mode != EvalRunMode.SINGLE_SHOT
    compaction_mode = {
        EvalRunMode.NO_COMPACTION: "none",
        EvalRunMode.NAIVE_COMPACTION: "naive",
    }.get(mode, "structured")
    return EvalRunConfig(
        run_id=make_run_id(mode.value),
        mode=mode,
        provider_id=provider_id,
        model_id=model_id,
        planning_enabled=planning_enabled,
        repair_enabled=repair_enabled,
        compaction_mode=compaction_mode,
        context_budget=context_budget,
        max_repairs=0 if not repair_enabled else 3,
    )


def _resolve_llm_config() -> dict[str, str]:
    config = _load_local_secrets(SECRETS_PATH)
    config.update(
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith("CODETEAM_LLM_")
        }
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
            f"Set them in {SECRETS_PATH} or environment variables."
        )
    return config


def _load_local_secrets(path: Path) -> dict[str, str]:
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


def _make_complete(config: dict[str, str]):
    client = OpenAICompatibleClient(
        model=config["CODETEAM_LLM_MODEL"],
        request_func=lambda messages: _chat_completion_request(config, messages),
    )

    def complete(messages: list[Message]) -> str:
        response = client.complete(messages)
        return response.content if isinstance(response, ModelResponse) else response

    return complete


def _chat_completion_request(
    config: dict[str, str],
    messages: list[Message],
    *,
    sleep_func=time.sleep,
) -> str:
    return _chat_completion_model_response(
        config,
        messages,
        sleep_func=sleep_func,
    ).content


def _chat_completion_model_response(
    config: dict[str, str],
    messages: list[Message],
    *,
    sleep_func=time.sleep,
) -> ModelResponse:
    body = json.dumps(
        {
            "model": config["CODETEAM_LLM_MODEL"],
            "messages": [_provider_message(message) for message in messages],
        }
    ).encode("utf-8")
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
    failures: list[ProviderAttemptFailure] = []

    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            f"{config['CODETEAM_LLM_BASE_URL'].rstrip('/')}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {config['CODETEAM_LLM_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                data = json.loads(response.read())
            usage = data.get("usage") or {}
            return ModelResponse(
                content=data["choices"][0]["message"]["content"],
                model=str(data.get("model") or config["CODETEAM_LLM_MODEL"]),
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            )
        except Exception as error:
            failure = _classify_provider_failure(error, attempt=attempt)
            failures.append(failure)
            if not failure.retryable or attempt >= max_attempts:
                raise ProviderRequestError(failures) from error
            sleep_func(backoff_seconds * (2 ** (attempt - 1)))

    raise ProviderRequestError(failures)


def _provider_message(message: Message) -> dict[str, str | None]:
    """Serialize the custom JSON protocol without native tool-call coupling."""
    if message.role == "tool":
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


def _classify_provider_failure(
    error: Exception,
    *,
    attempt: int,
) -> ProviderAttemptFailure:
    if isinstance(error, urllib.error.HTTPError):
        body = _read_http_error_body(error)
        message = body or str(error)
        if error.code == 429:
            return ProviderAttemptFailure(
                attempt=attempt,
                category="rate_limit",
                retryable=True,
                message=message,
                status_code=error.code,
            )
        if error.code in {408, 504}:
            return ProviderAttemptFailure(
                attempt=attempt,
                category="timeout",
                retryable=True,
                message=message,
                status_code=error.code,
            )
        if error.code in {500, 502, 503}:
            return ProviderAttemptFailure(
                attempt=attempt,
                category="server",
                retryable=True,
                message=message,
                status_code=error.code,
            )
        if error.code in {401, 403}:
            return ProviderAttemptFailure(
                attempt=attempt,
                category="auth",
                retryable=False,
                message=message,
                status_code=error.code,
            )
        return ProviderAttemptFailure(
            attempt=attempt,
            category="invalid_request" if error.code == 400 else "http",
            retryable=False,
            message=message,
            status_code=error.code,
        )

    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        category = _network_failure_category(reason)
        return ProviderAttemptFailure(
            attempt=attempt,
            category=category,
            retryable=category in {"timeout", "ssl_eof", "network"},
            message=str(reason),
        )

    if isinstance(error, TimeoutError | socket.timeout):
        return ProviderAttemptFailure(
            attempt=attempt,
            category="timeout",
            retryable=True,
            message=str(error),
        )

    if isinstance(error, ssl.SSLError):
        category = "ssl_eof" if _looks_like_ssl_eof(error) else "ssl"
        return ProviderAttemptFailure(
            attempt=attempt,
            category=category,
            retryable=category == "ssl_eof",
            message=str(error),
        )

    if isinstance(error, OSError):
        category = _network_failure_category(error)
        return ProviderAttemptFailure(
            attempt=attempt,
            category=category,
            retryable=category in {"timeout", "ssl_eof", "network"},
            message=str(error),
        )

    return ProviderAttemptFailure(
        attempt=attempt,
        category="unknown",
        retryable=False,
        message=f"{type(error).__name__}: {error}",
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
    if (
        "nodename nor servname provided" in text
        or "name or service not known" in text
        or "temporary failure in name resolution" in text
        or "getaddrinfo" in text
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
