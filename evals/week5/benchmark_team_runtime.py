"""Weekend-only deterministic Team orchestration benchmark (no LLM/API)."""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
)
from codeteam.agent_team.models import (
    AgentRole,
    LeadPlanningResult,
    WorkerAssignment,
)
from codeteam.agent_team.team_planning import StaticTeamPlanner, TeamPlan
from codeteam.agent_team.team_runtime import TeamCodingRuntime
from codeteam.agent_team.team_runtime_provider import (
    LocalTeamRuntimeProvider,
)
from codeteam.agent_team.worker_executor import WorkerExecutor
from codeteam.planning.models import Plan, PlanStep


class TimedScriptedRuntime:
    def __init__(self, work_seconds: float) -> None:
        self._work_seconds = work_seconds

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        time.sleep(self._work_seconds)
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.COMPLETED,
            summary="deterministic benchmark work complete",
            workspace_root=request.workspace_root,
            steps_used=1,
            tool_calls_used=1,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", default="1,3")
    parser.add_argument("--workloads", default="linear,diamond,fanout,layered")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--work-seconds", type=float, default=0.02)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    workers = tuple(int(item) for item in args.workers.split(","))
    workloads = tuple(item.strip() for item in args.workloads.split(","))
    if any(item not in {1, 3} for item in workers):
        raise SystemExit("deterministic benchmark supports workers=1 or 3")
    if args.iterations < 1 or args.warmup < 0 or args.work_seconds < 0:
        raise SystemExit("invalid benchmark iteration/warmup/work duration")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, object]] = []
    for workload in workloads:
        plan = _workload_plan(workload)
        for worker_count in workers:
            for iteration in range(args.warmup + args.iterations):
                with tempfile.TemporaryDirectory(prefix="codeteam-day7-") as raw:
                    root = Path(raw)
                    workspace = root / "workspace"
                    workspace.mkdir()
                    request = CodingAgentRunRequest(
                        task_id=f"bench-{workload}",
                        task=f"Run deterministic {workload} workload.",
                        workspace_root=workspace,
                        provider_id="scripted",
                        model_id="scripted",
                        max_steps=100,
                        max_tool_calls=200,
                        max_repairs=20,
                    )
                    runtime = TeamCodingRuntime(
                        planner=StaticTeamPlanner(plan),
                        worker_executor=WorkerExecutor(
                            TimedScriptedRuntime(args.work_seconds)
                        ),
                        runtime_provider=LocalTeamRuntimeProvider(root / "state"),
                        max_workers=worker_count,
                    )
                    result = runtime.run_team(request)
                if result.runtime_result.status is not RuntimeStatus.COMPLETED:
                    raise RuntimeError("correctness gate failed during benchmark")
                if iteration < args.warmup:
                    continue
                samples.append(
                    {
                        "workload": workload,
                        "workers": worker_count,
                        "iteration": iteration - args.warmup,
                        "wall_seconds": result.artifact.metrics.wall_seconds,
                        "aggregate_worker_seconds": (
                            result.artifact.metrics.aggregate_worker_seconds
                        ),
                        "scheduler_wait_seconds": (
                            result.artifact.metrics.scheduler_wait_seconds
                        ),
                        "max_parallelism": result.artifact.metrics.max_parallelism,
                        "utilization": result.artifact.metrics.utilization,
                        "retries": result.artifact.metrics.retries,
                        "messages": result.artifact.metrics.messages_sent,
                        "budget": result.artifact.budget.model_dump(mode="json"),
                        "usage": result.artifact.budget_usage.model_dump(mode="json"),
                        "correctness": True,
                    }
                )

    (output / "raw_samples.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in samples),
        encoding="utf-8",
    )
    summary = _summarize(samples)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "benchmark": "deterministic_team_runtime",
        "workers": workers,
        "workloads": workloads,
        "iterations": args.iterations,
        "warmup": args.warmup,
        "work_seconds": args.work_seconds,
        "python": sys.version,
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "head_commit": _git_output("rev-parse", "HEAD"),
        "dirty": bool(_git_output("status", "--porcelain")),
        "real_llm": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _workload_plan(name: str) -> TeamPlan:
    definitions: dict[str, tuple[tuple[str, AgentRole, tuple[str, ...]], ...]] = {
        "linear": (
            ("A", AgentRole.GENERAL, ("read",)),
            ("B", AgentRole.BACKEND, ("python",)),
            ("C", AgentRole.TEST, ("pytest",)),
        ),
        "diamond": (
            ("A", AgentRole.GENERAL, ("read",)),
            ("B", AgentRole.BACKEND, ("python",)),
            ("C", AgentRole.TEST, ("pytest",)),
            ("D", AgentRole.GENERAL, ("read",)),
        ),
        "fanout": (
            ("A", AgentRole.GENERAL, ("read",)),
            ("B", AgentRole.BACKEND, ("python",)),
            ("C", AgentRole.TEST, ("pytest",)),
            ("D", AgentRole.GENERAL, ("search",)),
            ("E", AgentRole.GENERAL, ("read",)),
        ),
        "layered": (
            ("A", AgentRole.GENERAL, ("read",)),
            ("B", AgentRole.BACKEND, ("python",)),
            ("C", AgentRole.TEST, ("pytest",)),
            ("D", AgentRole.GENERAL, ("search",)),
            ("E", AgentRole.BACKEND, ("api",)),
            ("F", AgentRole.GENERAL, ("read",)),
        ),
    }
    if name not in definitions:
        raise SystemExit(f"unknown workload: {name}")
    edges = {
        "linear": (("A", "B"), ("B", "C")),
        "diamond": (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")),
        "fanout": (
            ("A", "B"),
            ("A", "C"),
            ("A", "D"),
            ("B", "E"),
            ("C", "E"),
            ("D", "E"),
        ),
        "layered": (
            ("A", "B"),
            ("A", "C"),
            ("A", "D"),
            ("B", "E"),
            ("C", "E"),
            ("D", "E"),
            ("E", "F"),
        ),
    }[name]
    steps = tuple(
        PlanStep(step_id=node_id, title=node_id, description=f"Work {node_id}")
        for node_id, _, _ in definitions[name]
    )
    assignments = tuple(
        WorkerAssignment(
            assignment_id=node_id,
            task_id=f"bench-{name}",
            source_step_id=node_id,
            role=role,
            goal=f"Work {node_id}",
            expected_output=f"Result {node_id}",
            required_capabilities=capabilities,
            allow_workspace_write=False,
            budget_weight=1,
        )
        for node_id, role, capabilities in definitions[name]
    )
    return TeamPlan(
        lead_result=LeadPlanningResult(
            task_id=f"bench-{name}",
            plan=Plan(
                plan_id=f"plan-{name}",
                task_id=f"bench-{name}",
                steps=steps,
            ),
            assignments=assignments,
        ),
        dependencies=edges,
    )


def _summarize(samples: list[dict[str, object]]) -> dict[str, object]:
    groups: dict[tuple[str, int], list[float]] = {}
    for sample in samples:
        key = (str(sample["workload"]), int(sample["workers"]))
        groups.setdefault(key, []).append(float(sample["wall_seconds"]))
    return {
        f"{workload}:workers={workers}": {
            "count": len(values),
            "mean_wall_seconds": mean(values),
            "p50_wall_seconds": median(values),
            "p95_wall_seconds": _percentile(values, 0.95),
        }
        for (workload, workers), values in sorted(groups.items())
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return ordered[index]


def _git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        shell=False,
        timeout=10,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


if __name__ == "__main__":
    raise SystemExit(main())
