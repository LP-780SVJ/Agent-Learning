from __future__ import annotations

from datetime import UTC, datetime

from codeteam.agent_team.contracts import LifecyclePolicy
from codeteam.agent_team.dag import TaskNode, TaskStatus
from codeteam.agent_team.mailbox import AgentMessage, AgentMessageType
from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentRole,
    AgentStatus,
    WorkerAssignment,
)
from codeteam.agent_team.persistence_models import (
    DurableMessage,
    DurableWorkerState,
    TeamStateSnapshot,
)
from codeteam.agent_team.scheduler import TaskRuntimeRecord
from codeteam.session.models import RepositoryRef, Session, SessionManifest
from codeteam.task.models import TaskSpec


def assignment(node_id: str) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=node_id,
        task_id="task-1",
        source_step_id=f"step-{node_id}",
        role=AgentRole.BACKEND,
        goal=f"Implement {node_id}",
        expected_output=f"{node_id} complete",
    )


def team_snapshot(*, session_id: str = "ses_team_test") -> TeamStateSnapshot:
    worker_identity = AgentIdentity(agent_id="worker-1", display_name="Worker 1")
    lead_identity = AgentIdentity(agent_id="lead-1", display_name="Lead 1")
    message = AgentMessage(
        message_id="msg-1",
        sender_id=lead_identity.agent_id,
        recipient_id=worker_identity.agent_id,
        message_type=AgentMessageType.TASK_ASSIGNED,
        task_id="task-1",
        node_id="A",
        correlation_id="corr-1",
        payload={"goal": "A"},
        created_at=1.0,
    )
    return TeamStateSnapshot(
        session_id=session_id,
        dag_nodes=(
            TaskNode(node_id="A", assignment=assignment("A")),
            TaskNode(node_id="B", assignment=assignment("B")),
        ),
        dependencies={"A": frozenset(), "B": frozenset({"A"})},
        tasks={
            "A": TaskRuntimeRecord(node_id="A", status=TaskStatus.READY),
            "B": TaskRuntimeRecord(node_id="B", status=TaskStatus.PENDING),
        },
        workers={
            "worker-1": DurableWorkerState(
                info=AgentInfo(
                    identity=worker_identity,
                    role=AgentRole.BACKEND,
                    status=AgentStatus.READY,
                ),
                status=AgentStatus.READY,
                generation=2,
                revision=4,
                restart_attempts=1,
                restart_not_before_utc=datetime(2030, 1, 1, tzinfo=UTC),
            )
        },
        ready_queue=("A",),
        worker_ownership={"worker-1": None},
        mailbox_agents=(lead_identity, worker_identity),
        messages=(DurableMessage(message=message, enqueue_seq=1),),
        seen_message_ids=frozenset({"msg-1", "msg-consumed"}),
        max_attempts=2,
        lifecycle_policy=LifecyclePolicy(
            heartbeat_timeout_seconds=15,
            restart_cooldown_seconds=3,
            max_restarts=4,
        ),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def session_for_team(*, session_id: str = "ses_team_test") -> Session:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return Session(
        manifest=SessionManifest(
            session_id=session_id,
            repo_id="repo-1",
            created_at=now,
            updated_at=now,
        ),
        task=TaskSpec(
            task_id="task-1",
            original_request="Implement team persistence",
            goal="Implement team persistence",
        ),
        provider_id="mock-provider",
        model_id="mock-model",
        repo=RepositoryRef(
            repo_id="repo-1",
            git_common_dir="/tmp/repo/.git",
            base_sha="a" * 40,
        ),
    )
