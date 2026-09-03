from pathlib import Path

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeArtifactRef,
    RuntimeStatus,
)
from codeteam.agent_team.team_runtime import TeamResultProtocolError
from codeteam.evaluation.agent_models import EvalRunConfig
from codeteam.evaluation.agent_runner import (
    _invoke_runtime,
    _runtime_to_actor_result,
    _save_runtime_artifacts,
)


class RejectingTeamRuntime:
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        del request
        raise TeamResultProtocolError("stale attempt")


def test_team_common_result_uses_the_existing_evaluator_contract(tmp_path: Path) -> None:
    result = CodingAgentRunResult(
        task_id="B01",
        status=RuntimeStatus.COMPLETED,
        summary="Team completed all nodes.",
        workspace_root=tmp_path,
        changed_files=("app.py",),
        artifacts=(
            RuntimeArtifactRef(
                kind="team_run",
                session_id="team-session-1",
                path=Path("artifacts/team_run.json"),
                sha256="a" * 64,
            ),
        ),
    )

    actor = _runtime_to_actor_result(result, EvalRunConfig(run_id="team-test"))
    paths = _save_runtime_artifacts(output_dir=tmp_path / "out", result=result)

    assert actor.status.value == "completed"
    assert actor.changed_files == ("app.py",)
    assert paths[-1] == "team-session-1/artifacts/team_run.json"


def test_team_protocol_error_becomes_structured_eval_failure(tmp_path: Path) -> None:
    request = CodingAgentRunRequest(
        task_id="B01",
        task="Run Team task.",
        workspace_root=tmp_path,
        provider_id="scripted",
        model_id="scripted",
    )

    result = _invoke_runtime(RejectingTeamRuntime(), request)

    assert result.status is RuntimeStatus.FAILED
    assert result.failure_category == "team_runtime_protocol_failure"
    assert "stale attempt" in (result.error or "")
