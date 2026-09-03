import re
from pathlib import Path

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
)
from codeteam.agent_team.models import AgentRole, WorkerAssignment
from codeteam.agent_team.scheduler import TaskClaim
from codeteam.agent_team.team_models import NodeBudgetAllocation
from codeteam.agent_team.worker_executor import (
    WorkerExecutionRequest,
    WorkerExecutor,
)


class CapturingRuntime:
    def __init__(self) -> None:
        self.requests: list[CodingAgentRunRequest] = []

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        self.requests.append(request)
        return CodingAgentRunResult(
            task_id=request.task_id,
            status=RuntimeStatus.COMPLETED,
            summary="done",
            workspace_root=request.workspace_root,
            steps_used=2,
            tool_calls_used=3,
        )


def test_worker_executor_revalidates_bounded_read_only_child_request(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = CapturingRuntime()
    executor = WorkerExecutor(runtime)
    assignment = WorkerAssignment(
        assignment_id="review",
        task_id="task-1",
        source_step_id="review",
        role=AgentRole.REVIEW,
        goal="Review the change.",
        expected_output="Review findings.",
        required_capabilities=("review",),
        allow_workspace_write=False,
        budget_weight=1,
    )
    result = executor.execute(
        WorkerExecutionRequest(
            parent_request=CodingAgentRunRequest(
                task_id="task-1",
                task="Parent task",
                workspace_root=workspace,
                provider_id="scripted",
                model_id="scripted",
                max_steps=20,
                max_tool_calls=40,
            ),
            assignment=assignment,
            claim=TaskClaim(
                node_id="review",
                worker_id="worker-test-1",
                attempt=1,
                claimed_at=1.0,
                runtime_id="runtime-1",
                worker_generation=1,
            ),
            workspace_root=workspace,
            budget=NodeBudgetAllocation(
                node_id="review",
                weight=1,
                max_steps=5,
                max_tool_calls=8,
                max_repairs=1,
                max_protocol_repairs=1,
            ),
            ready_at=0.5,
        )
    )

    child = runtime.requests[0]
    assert result.status is RuntimeStatus.COMPLETED
    assert child.task_id.startswith("task-1-review-attempt-1-")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", child.task_id)
    assert child.max_steps == 5
    assert child.max_tool_calls == 8
    assert child.workspace_write_allowed is False
    assert child.initial_messages == ()


def test_worker_executor_child_task_id_is_safe_stable_and_collision_resistant(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = CapturingRuntime()
    executor = WorkerExecutor(runtime)
    assignment = WorkerAssignment(
        assignment_id="node/backend:implementation",
        task_id="B01:unsafe/path",
        source_step_id="implementation",
        role=AgentRole.BACKEND,
        goal="Implement the change.",
        expected_output="Verified patch.",
        required_capabilities=("python", "patch"),
        budget_weight=1,
    )

    def build(attempt: int) -> CodingAgentRunRequest:
        return executor.build_runtime_request(
            WorkerExecutionRequest(
                parent_request=CodingAgentRunRequest(
                    task_id="B01:unsafe/path",
                    task="Parent task",
                    workspace_root=workspace,
                    provider_id="scripted",
                    model_id="scripted",
                ),
                assignment=assignment,
                claim=TaskClaim(
                    node_id=assignment.assignment_id,
                    worker_id="worker-backend-1",
                    attempt=attempt,
                    claimed_at=1.0,
                    runtime_id="runtime-1",
                    worker_generation=1,
                ),
                workspace_root=workspace,
                budget=NodeBudgetAllocation(
                    node_id=assignment.assignment_id,
                    weight=1,
                    max_steps=5,
                    max_tool_calls=8,
                    max_repairs=1,
                    max_protocol_repairs=1,
                ),
                ready_at=0.5,
            )
        )

    first = build(1).task_id
    repeated = build(1).task_id
    second_attempt = build(2).task_id

    assert first == repeated
    assert first != second_attempt
    assert len(first) <= 93
    assert re.fullmatch(r"[A-Za-z0-9._-]+", first)
    assert not first.startswith(".")
    assert ".." not in first
