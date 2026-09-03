"""Subprocess helper that crashes after a durable Task enters RUNNING."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
)
from codeteam.agent_team.team_planning import (
    DeterministicSingleNodePlanner,
)
from codeteam.agent_team.team_runtime import TeamCodingRuntime
from codeteam.agent_team.team_runtime_provider import (
    LocalTeamRuntimeProvider,
)
from codeteam.agent_team.worker_executor import WorkerExecutor


class ProcessCrashRuntime:
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        del request
        os._exit(73)


def main() -> None:
    workspace = Path(sys.argv[1])
    state_root = Path(sys.argv[2])
    TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(ProcessCrashRuntime()),
        runtime_provider=LocalTeamRuntimeProvider(state_root),
    ).run_team(
        CodingAgentRunRequest(
            task_id="B01",
            task="Crash during Worker execution.",
            workspace_root=workspace,
            provider_id="scripted",
            model_id="scripted",
            max_steps=20,
            max_tool_calls=40,
        )
    )


if __name__ == "__main__":
    main()
