"""Manual B01 Team Runtime smoke; dry-run never constructs a provider client."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent.runtime_models import CodingAgentRunRequest
from codeteam.agent_team.team_budget import WeightedTeamBudgetPolicy
from codeteam.agent_team.team_planning import (
    DeterministicSingleNodePlanner,
)
from codeteam.agent_team.team_runtime import TeamCodingRuntime
from codeteam.agent_team.team_runtime_provider import (
    LocalTeamRuntimeProvider,
)
from codeteam.agent_team.worker_executor import WorkerExecutor
from codeteam.agent_team.worker_pool import (
    assignment_compatibility_rank,
    static_worker_infos,
)
from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import EvalRunConfig
from codeteam.evaluation.agent_runner import (
    AgentEvalRunner,
    filter_agent_eval_tasks,
    load_agent_eval_tasks,
    make_run_id,
)
from codeteam.git.worktree_paths import resolve_worktree_root
from codeteam.llm.openai_compatible import (
    build_openai_compatible_client,
    provider_manifest,
    resolve_llm_config,
)
from codeteam.redaction import (
    redact_sensitive_data,
    redact_sensitive_text,
    safe_exception_details,
)

SECRETS_PATH = PROJECT_ROOT / "secrets.local.env"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--task-id", default="B01")
    parser.add_argument("--runtime", choices=("team",), default="team")
    parser.add_argument(
        "--provider", choices=("openai-compatible",), default="openai-compatible"
    )
    parser.add_argument(
        "--plan",
        choices=("deterministic-single-node",),
        default="deterministic-single-node",
    )
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--context-budget", type=int, default=4096)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--model-context-window", type=int, default=32768)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-tool-calls", type=int, default=40)
    parser.add_argument("--max-repairs", type=int, default=3)
    parser.add_argument("--max-protocol-repairs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--worktree-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-workspaces", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_fixed_smoke_contract(args)
    suite = args.suite if args.suite.is_absolute() else PROJECT_ROOT / args.suite
    selected = filter_agent_eval_tasks(
        load_agent_eval_tasks(suite),
        task_ids={args.task_id},
    )
    if len(selected) != 1 or selected[0].task_id != "B01":
        raise SystemExit("Day7 real smoke is fixed to exactly one B01 task")

    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    backend = next(
        info
        for info in static_worker_infos()
        if info.identity.agent_id == "worker-backend-1"
    )
    request = CodingAgentRunRequest(
        task_id="B01",
        task=selected[0].prompt,
        workspace_root=output / "_dry_workspace",
        provider_id=args.provider,
        model_id=os.environ.get("CODETEAM_LLM_MODEL", "resolved-at-real-run"),
        context_budget=args.context_budget,
        max_output_tokens=args.max_output_tokens,
        model_context_window=args.model_context_window,
        max_steps=args.max_steps,
        max_tool_calls=args.max_tool_calls,
        max_repairs=args.max_repairs,
        max_protocol_repairs=args.max_protocol_repairs,
    )
    planner = DeterministicSingleNodePlanner()
    plan = planner.plan(request)
    assignment = plan.lead_result.assignments[0]
    allocation = WeightedTeamBudgetPolicy().allocate(
        parent=request,
        assignments=plan.lead_result.assignments,
    )
    if assignment_compatibility_rank(assignment, backend) != 0:
        raise SystemExit("B01 assignment is not compatible with backend Worker")

    run_id = make_run_id("day7-b01-team-smoke")
    smoke_manifest: dict[str, object] = {
        "schema_version": 1,
        "evidence_scope": "single-worker Team wiring smoke; not a multi-worker benchmark",
        "task_id": "B01",
        "run_id": run_id,
        "suite": str(args.suite),
        "runtime": args.runtime,
        "provider": args.provider,
        "model": request.model_id,
        "temperature": os.environ.get("CODETEAM_LLM_TEMPERATURE", "0"),
        "response_mode": os.environ.get("CODETEAM_LLM_RESPONSE_MODE", "auto"),
        "planner": args.plan,
        "worker_count": args.worker_count,
        "max_concurrency": args.max_concurrency,
        "worker": backend.model_dump(mode="json"),
        "assignment": assignment.model_dump(mode="json"),
        "dependencies": plan.dependencies,
        "budget": allocation.model_dump(mode="json"),
        "timeout_seconds": args.timeout_seconds,
        "output": str(output),
        "network_call_performed": False,
        "real_llm_result": "NOT_RUN" if args.dry_run else "STARTED",
        "started_at": _utc_now(),
        "finished_at": None,
        "success": None,
        "artifacts": {
            "results": "results.jsonl",
            "summary": "summary.json",
            "runner_manifest": "manifest.json",
        },
    }
    manifest_path = output / "team_smoke_manifest.json"
    _atomic_write_manifest(manifest_path, smoke_manifest)
    if args.dry_run:
        print(json.dumps(smoke_manifest, ensure_ascii=False, indent=2))
        return 0

    try:
        llm_config = resolve_llm_config(SECRETS_PATH)
        smoke_manifest["model"] = llm_config["CODETEAM_LLM_MODEL"]
        smoke_manifest["network_call_performed"] = True
        _atomic_write_manifest(manifest_path, smoke_manifest)
        coding_runtime = CodingAgentRuntime(
            model_client=build_openai_compatible_client(llm_config)
        )
        team_runtime = TeamCodingRuntime(
            planner=planner,
            worker_executor=WorkerExecutor(coding_runtime),
            runtime_provider=LocalTeamRuntimeProvider(
                output / "team_state",
                worker_infos=(backend,),
            ),
            max_workers=1,
        )
        runner = AgentEvalRunner(
            project_root=PROJECT_ROOT,
            runtime=team_runtime,
            grader=AgentGrader(project_root=PROJECT_ROOT),
            keep_workspaces=args.keep_workspaces,
            worktree_root=resolve_worktree_root(args.worktree_root),
            provider_metadata=lambda: provider_manifest(llm_config),
        )
        results = runner.run_suite(
            tasks=selected,
            config=EvalRunConfig(
                run_id=run_id,
                provider_id=args.provider,
                model_id=llm_config["CODETEAM_LLM_MODEL"],
                context_budget=args.context_budget,
                max_output_tokens=args.max_output_tokens,
                model_context_window=args.model_context_window,
                max_steps=args.max_steps,
                max_tool_calls=args.max_tool_calls,
                max_repairs=args.max_repairs,
                max_protocol_repairs=args.max_protocol_repairs,
                task_timeout_seconds=args.timeout_seconds,
            ),
            output_dir=output,
        )
    except BaseException as error:
        details = safe_exception_details(error, code="smoke_runner_exception")
        smoke_manifest.update(
            {
                "real_llm_result": "FAILED",
                "finished_at": _utc_now(),
                "success": False,
                "failure": {
                    "category": details.code,
                    "origin": "smoke_team_runtime",
                    "exception_type": details.exception_type,
                    "message": details.message,
                    "summary_sha256": details.summary_sha256,
                },
            }
        )
        try:
            _atomic_write_manifest(manifest_path, smoke_manifest)
        except BaseException as manifest_error:  # noqa: BLE001 - preserve interrupt.
            error.add_note(
                "Failed to persist terminal smoke manifest: "
                f"{type(manifest_error).__name__}"
            )
        raise

    success = bool(results) and all(result.success for result in results)
    first = results[0]
    failure = None
    if not success:
        failure = {
            "category": getattr(first, "failure_category", None)
            or "evaluation_failed",
            "origin": getattr(first, "failure_origin", None) or "agent_eval",
            "message": redact_sensitive_text(
                getattr(first, "error", None) or "B01 evaluation did not pass."
            ),
        }
    smoke_manifest.update(
        {
            "real_llm_result": "COMPLETED" if success else "FAILED",
            "finished_at": _utc_now(),
            "success": success,
            "failure": failure,
        }
    )
    _atomic_write_manifest(manifest_path, smoke_manifest)
    print(results[0].model_dump_json(indent=2))
    return 0 if success else 1


def _atomic_write_manifest(path: Path, payload: dict[str, object]) -> None:
    """Replace a complete manifest without exposing a partial JSON document."""

    sanitized = redact_sensitive_data(payload)
    encoded = (
        json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_fixed_smoke_contract(args: argparse.Namespace) -> None:
    if args.worker_count != 1 or args.max_concurrency != 1:
        raise SystemExit(
            "Week5 real Team smoke requires worker-count=1 and max-concurrency=1"
        )
    positive = {
        "context_budget": args.context_budget,
        "max_output_tokens": args.max_output_tokens,
        "model_context_window": args.model_context_window,
        "max_steps": args.max_steps,
        "max_tool_calls": args.max_tool_calls,
        "timeout_seconds": args.timeout_seconds,
    }
    if any(value < 1 for value in positive.values()):
        raise SystemExit("all smoke budgets and timeout must be positive")


if __name__ == "__main__":
    raise SystemExit(main())
