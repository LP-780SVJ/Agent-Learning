"""CLI command for task-level agent coding evaluation."""
from __future__ import annotations

import json
import os
import urllib.request
from argparse import Namespace
from pathlib import Path

from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import AgentEvalSplit, EvalRunConfig, EvalRunMode
from codeteam.evaluation.agent_runner import (
    AgentEvalRunner,
    filter_agent_eval_tasks,
    load_agent_eval_tasks,
    make_run_id,
    summarize_agent_eval_results,
)
from codeteam.evaluation.patch_actor import (
    LLMPatchGenerator,
    NullPatchGenerator,
    PatchActor,
    PatchGenerator,
)
from codeteam.llm.openai_compatible import OpenAICompatibleClient
from codeteam.schemas.messages import Message

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_PATH = PROJECT_ROOT / "secrets.local.env"


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
    planner_complete = None
    patch_generator: PatchGenerator
    if args.actor == "llm":
        llm_config = _resolve_llm_config()
        provider_id = "openai-compatible"
        model_id = llm_config["CODETEAM_LLM_MODEL"]
        complete = _make_complete(llm_config)
        patch_generator = LLMPatchGenerator(
            complete=complete,
            model_id=model_id,
        )
        planner_complete = complete
    elif args.actor == "null":
        patch_generator = NullPatchGenerator()
    else:
        raise SystemExit(f"Unknown actor: {args.actor}")

    actor = PatchActor(
        patch_generator=patch_generator,
        planner_complete=planner_complete,
    )
    grader = AgentGrader(project_root=PROJECT_ROOT)
    runner = AgentEvalRunner(
        project_root=PROJECT_ROOT,
        actor=actor,
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
        return client.complete(messages)

    return complete


def _chat_completion_request(
    config: dict[str, str],
    messages: list[Message],
) -> str:
    body = json.dumps(
        {
            "model": config["CODETEAM_LLM_MODEL"],
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config['CODETEAM_LLM_BASE_URL'].rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config['CODETEAM_LLM_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read())
    return data["choices"][0]["message"]["content"]
