from pathlib import Path

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
)
from codeteam.evaluation.agent_models import EvalRunConfig
from codeteam.evaluation.agent_runner import AgentEvalRunner, load_agent_eval_tasks


class RecordingNullRuntime:
    def __init__(self) -> None:
        self.requests: list[CodingAgentRunRequest] = []

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        self.requests.append(request)
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.FAILED,
            summary="null baseline",
            workspace_root=request.workspace_root,
            failure_category="no_patch",
            error="null baseline",
        )


def test_week4_public_oracles_fail_pristine_and_null_baseline_is_zero(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    tasks = load_agent_eval_tasks(
        project_root / "evals" / "week4" / "agent_task_suite_v1.jsonl"
    )
    runtime = RecordingNullRuntime()
    results = AgentEvalRunner(
        project_root=project_root,
        runtime=runtime,
        keep_workspaces=False,
        worktree_root=tmp_path / "worktrees",
    ).run_suite(
        tasks=tasks,
        config=EvalRunConfig(run_id="null-public-oracle"),
        output_dir=tmp_path / "out",
    )

    assert len(results) == 11
    assert sum(result.success for result in results) == 0
    assert not any(result.pristine_task_verification_passed for result in results)
    assert all(request.task_verification_commands for request in runtime.requests)
    assert all(
        "eval_hidden" not in request.model_dump_json()
        for request in runtime.requests
    )
