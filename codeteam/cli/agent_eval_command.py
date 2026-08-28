"""Thin CLI command for task-level agent coding evaluation."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import (
    AgentEvalSplit,
    EvalRunConfig,
    EvalRunMode,
    PatchActorStatus,
)
from codeteam.evaluation.agent_runner import (
    AgentEvalRunner,
    filter_agent_eval_tasks,
    load_agent_eval_tasks,
    make_run_id,
    summarize_agent_eval_results,
)
from codeteam.git.worktree_paths import resolve_worktree_root
from codeteam.llm import openai_compatible as provider_adapter
from codeteam.llm.base import ModelClient, ModelResponse
from codeteam.llm.openai_compatible import (
    OpenAICompatibleClient,
    build_openai_compatible_client,
    legacy_chat_completion_model_response,
    legacy_chat_completion_request,
    load_local_secrets,
    provider_manifest,
    resolve_llm_config,
)
from codeteam.schemas.messages import Message

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_PATH = PROJECT_ROOT / "secrets.local.env"

# Compatibility exports for historical tests and PatchActor.  They are aliases
# only; provider implementation and state live in codeteam.llm.
urllib = provider_adapter.urllib
ProviderAttemptFailure = provider_adapter.ProviderAttemptFailure
ProviderRequestError = provider_adapter.ProviderRequestError
_JSON_MODE_CAPABILITY = provider_adapter._JSON_MODE_CAPABILITY
_NATIVE_TOOL_CAPABILITY = provider_adapter._NATIVE_TOOL_CAPABILITY
_THINKING_CONTROL_CAPABILITY = provider_adapter._THINKING_CONTROL_CAPABILITY
_PROVIDER_RUNTIME_STATE = provider_adapter._PROVIDER_RUNTIME_STATE
_provider_message = provider_adapter._provider_message


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
    return build_openai_compatible_client(config)


def run_agent_eval(args: Namespace) -> None:
    tasks = load_agent_eval_tasks(Path(args.suite))
    split = AgentEvalSplit(args.split) if args.split else None
    selected = filter_agent_eval_tasks(
        tasks,
        split=split,
        task_ids=set(args.task_id or []) or None,
        limit=args.limit,
    )
    if not selected:
        raise SystemExit("No tasks selected.")

    provider_id = "openai-compatible"
    model_id = "null"
    model_client: ModelClient | _NullModelClient
    llm_config: dict[str, str] | None = None
    if args.actor == "llm":
        llm_config = _resolve_llm_config()
        model_id = llm_config["CODETEAM_LLM_MODEL"]
        model_client = make_runtime_model_client(llm_config)
    elif args.actor == "null":
        model_client = _NullModelClient()
    else:
        raise SystemExit(f"Unknown actor: {args.actor}")

    runtime = CodingAgentRuntime(model_client=model_client)
    runner = AgentEvalRunner(
        project_root=PROJECT_ROOT,
        runtime=runtime,
        grader=AgentGrader(project_root=PROJECT_ROOT),
        keep_workspaces=args.keep_workspaces,
        worktree_root=resolve_worktree_root(getattr(args, "worktree_root", None)),
        provider_metadata=(
            (lambda: provider_manifest(llm_config))
            if llm_config is not None
            else None
        ),
    )
    configs = _build_run_configs(
        mode=args.mode,
        provider_id=provider_id,
        model_id=model_id,
        context_budget=args.context_budget,
        max_output_tokens=getattr(args, "max_output_tokens", 4096),
        model_context_window=getattr(args, "model_context_window", 32768),
        safety_headroom_tokens=getattr(args, "safety_headroom_tokens", 1024),
        native_tools=getattr(args, "native_tools", True),
        reasoning_enabled=getattr(args, "reasoning_enabled", False),
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
        print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False))

    combined = {
        "runs": len(configs),
        "tasks_per_run": len(selected),
        "total_task_results": len(all_results),
        "success_count": sum(result.success for result in all_results),
        "provider_blocked_count": sum(
            result.failure_category == "provider_blocked" for result in all_results
        ),
        "environment_blocked_count": sum(
            result.actor_status is PatchActorStatus.ENVIRONMENT_BLOCKED
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
    max_output_tokens: int = 4096,
    model_context_window: int = 32768,
    safety_headroom_tokens: int = 1024,
    native_tools: bool = True,
    reasoning_enabled: bool = False,
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
            max_output_tokens=max_output_tokens,
            model_context_window=model_context_window,
            safety_headroom_tokens=safety_headroom_tokens,
            native_tools=native_tools,
            reasoning_enabled=reasoning_enabled,
        )
        for run_mode in modes
    ]


def _config_for_mode(
    mode: EvalRunMode,
    *,
    provider_id: str,
    model_id: str,
    context_budget: int,
    max_output_tokens: int = 4096,
    model_context_window: int = 32768,
    safety_headroom_tokens: int = 1024,
    native_tools: bool = True,
    reasoning_enabled: bool = False,
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
        max_output_tokens=max_output_tokens,
        model_context_window=model_context_window,
        safety_headroom_tokens=safety_headroom_tokens,
        native_tools=native_tools,
        reasoning_enabled=reasoning_enabled,
        max_repairs=0 if not repair_enabled else 3,
    )


def _resolve_llm_config() -> dict[str, str]:
    return resolve_llm_config(SECRETS_PATH)


def _load_local_secrets(path: Path) -> dict[str, str]:
    return load_local_secrets(path)


def _chat_completion_request(
    config: dict[str, str],
    messages: list[Message],
    *,
    sleep_func=provider_adapter.time.sleep,
) -> str:
    return legacy_chat_completion_request(config, messages, sleep_func=sleep_func)


def _chat_completion_model_response(
    config: dict[str, str],
    messages: list[Message],
    *,
    sleep_func=provider_adapter.time.sleep,
) -> ModelResponse:
    return legacy_chat_completion_model_response(
        config,
        messages,
        sleep_func=sleep_func,
    )


def _make_complete(config: dict[str, str]):
    client = OpenAICompatibleClient(
        model=config["CODETEAM_LLM_MODEL"],
        request_func=lambda messages: _chat_completion_request(config, messages),
    )

    def complete(messages: list[Message]) -> str:
        response = client.complete(messages)
        return response.content if isinstance(response, ModelResponse) else response

    return complete


def _provider_manifest(config: dict[str, str]) -> dict[str, object]:
    return provider_manifest(config)
