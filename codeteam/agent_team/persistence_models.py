"""Pydantic contracts for process-durable Multi-Agent state."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from codeteam.agent_team.contracts import LifecyclePolicy
from codeteam.agent_team.dag import TaskNode, TaskStatus
from codeteam.agent_team.mailbox import AgentMessage
from codeteam.agent_team.models import AgentIdentity, AgentInfo, AgentStatus
from codeteam.agent_team.scheduler import TaskRuntimeRecord

TEAM_STATE_SCHEMA_VERSION = 1


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class DurableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DurableWorkerState(DurableModel):
    info: AgentInfo
    status: AgentStatus
    generation: int = Field(ge=1, strict=True)
    revision: int = Field(ge=0, strict=True)
    restart_attempts: int = Field(ge=0, strict=True)
    restart_not_before_utc: datetime | None = None

    @field_validator("restart_not_before_utc")
    @classmethod
    def _deadline_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _aware(value, "restart_not_before_utc")


class DurableMessageState(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"


class DurableMessage(DurableModel):
    message: AgentMessage
    state: DurableMessageState = DurableMessageState.PENDING
    enqueue_seq: int = Field(ge=1, strict=True)
    delivery_attempt: int = Field(default=0, ge=0, strict=True)
    claimed_by_runtime_id: str | None = None
    claim_id: str | None = None

    @model_validator(mode="after")
    def _claim_fields_match_state(self) -> Self:
        claim_fields = (self.claimed_by_runtime_id, self.claim_id)
        if self.state is DurableMessageState.PENDING and any(
            item is not None for item in claim_fields
        ):
            raise ValueError("PENDING message cannot retain claim fields")
        if self.state is DurableMessageState.IN_FLIGHT and any(
            not item for item in claim_fields
        ):
            raise ValueError("IN_FLIGHT message requires runtime_id and claim_id")
        return self


class DurableEventDraft(DurableModel):
    event_type: str = Field(min_length=1)
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _payload_is_json_safe(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            json.dumps(value, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("durable event payload must be JSON-safe") from exc
        return value


class DurableEvent(DurableModel):
    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    seq: int = Field(ge=1, strict=True)
    revision: int = Field(ge=1, strict=True)
    event_type: str = Field(min_length=1)
    timestamp: datetime
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_is_aware(cls, value: datetime) -> datetime:
        return _aware(value, "timestamp")

    @field_validator("payload")
    @classmethod
    def _payload_is_json_safe(cls, value: dict[str, object]) -> dict[str, object]:
        return DurableEventDraft._payload_is_json_safe(value)


class MessageClaim(DurableModel):
    message: AgentMessage
    claim_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    delivery_attempt: int = Field(ge=1, strict=True)
    revision: int = Field(ge=1, strict=True)


class TeamStateSnapshot(DurableModel):
    schema_version: int = Field(default=TEAM_STATE_SCHEMA_VERSION, ge=1, strict=True)
    session_id: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1, strict=True)
    previous_runtime_id: str | None = None
    dag_nodes: tuple[TaskNode, ...]
    dependencies: dict[str, frozenset[str]]
    tasks: dict[str, TaskRuntimeRecord]
    workers: dict[str, DurableWorkerState]
    ready_queue: tuple[str, ...] = ()
    waiting_for_worker: frozenset[str] = frozenset()
    worker_ownership: dict[str, str | None] = Field(default_factory=dict)
    mailbox_agents: tuple[AgentIdentity, ...] = ()
    messages: tuple[DurableMessage, ...] = ()
    seen_message_ids: frozenset[str] = frozenset()
    mailbox_capacity: int = Field(default=1000, ge=1, strict=True)
    max_attempts: int = Field(default=1, ge=1, strict=True)
    lifecycle_policy: LifecyclePolicy = Field(default_factory=LifecyclePolicy)
    last_event_seq: int = Field(default=0, ge=0, strict=True)
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _updated_at_is_aware(cls, value: datetime) -> datetime:
        return _aware(value, "updated_at")

    @model_validator(mode="after")
    def _validate_runtime_graph(self) -> Self:
        # Nested model instances may have been built with model_copy(update=...),
        # so re-enter their formal validation boundary before graph checks.
        validated_tasks = {
            node_id: TaskRuntimeRecord.model_validate(record.model_dump())
            for node_id, record in self.tasks.items()
        }
        object.__setattr__(self, "tasks", validated_tasks)
        node_ids = [node.node_id for node in self.dag_nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("dag node ids must be unique")
        node_set = set(node_ids)
        if set(self.dependencies) != node_set:
            raise ValueError("dependencies must contain every DAG node exactly once")
        for dependent_id, prerequisites in self.dependencies.items():
            if dependent_id in prerequisites or not prerequisites <= node_set:
                raise ValueError("dependencies contain a self-edge or unknown node")
        # Kahn's algorithm is bounded by V + E and rejects cycles before a Store
        # can create a database file.
        indegrees = {
            node_id: len(prerequisites)
            for node_id, prerequisites in self.dependencies.items()
        }
        dependents: dict[str, list[str]] = {node_id: [] for node_id in node_set}
        for dependent_id, prerequisites in self.dependencies.items():
            for prerequisite_id in prerequisites:
                dependents[prerequisite_id].append(dependent_id)
        ready = [node_id for node_id, degree in indegrees.items() if degree == 0]
        visited = 0
        while ready:
            prerequisite_id = ready.pop()
            visited += 1
            for dependent_id in dependents[prerequisite_id]:
                indegrees[dependent_id] -= 1
                if indegrees[dependent_id] == 0:
                    ready.append(dependent_id)
        if visited != len(node_set):
            raise ValueError("dependencies must form an acyclic DAG")
        if set(self.tasks) != node_set:
            raise ValueError("tasks must contain every DAG node exactly once")
        if any(key != record.node_id for key, record in self.tasks.items()):
            raise ValueError("task map keys must match TaskRuntimeRecord.node_id")

        queue = self.ready_queue
        if len(queue) != len(set(queue)) or not set(queue) <= node_set:
            raise ValueError("ready_queue must be unique and reference known tasks")
        if any(self.tasks[node_id].status is not TaskStatus.READY for node_id in queue):
            raise ValueError("ready_queue may contain only READY tasks")
        ready_ids = {
            node_id
            for node_id, record in self.tasks.items()
            if record.status is TaskStatus.READY
        }
        if ready_ids != set(queue):
            raise ValueError("every READY task must appear in ready_queue")
        if not self.waiting_for_worker <= node_set or any(
            self.tasks[node_id].status is not TaskStatus.PENDING
            for node_id in self.waiting_for_worker
        ):
            raise ValueError("waiting tasks must be known PENDING tasks")

        if any(
            worker_id != worker.info.identity.agent_id
            for worker_id, worker in self.workers.items()
        ):
            raise ValueError("worker map keys must match worker identity agent_id")
        if set(self.worker_ownership) != set(self.workers):
            raise ValueError("worker_ownership must contain every worker")
        owned_nodes: set[str] = set()
        for worker_id, node_id in self.worker_ownership.items():
            worker = self.workers[worker_id]
            if node_id is None:
                if worker.status is AgentStatus.BUSY:
                    raise ValueError("BUSY worker must own one task")
                continue
            if node_id in owned_nodes or node_id not in self.tasks:
                raise ValueError("worker ownership must be unique and reference tasks")
            owned_nodes.add(node_id)
            task = self.tasks[node_id]
            if (
                worker.status is not AgentStatus.BUSY
                or task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}
                or task.owner_id != worker_id
                or task.owner_generation != worker.generation
            ):
                raise ValueError("worker ownership disagrees with worker/task state")
        for node_id, task in self.tasks.items():
            if task.status in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
                if task.owner_id is None or self.worker_ownership.get(task.owner_id) != node_id:
                    raise ValueError("in-flight task requires matching worker ownership")
            elif task.owner_id is not None or task.owner_generation is not None:
                raise ValueError("non-in-flight task cannot retain owner")

        agent_ids = [identity.agent_id for identity in self.mailbox_agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("mailbox agent ids must be unique")
        known_agents = set(agent_ids)
        message_ids: set[str] = set()
        enqueue_seqs: set[int] = set()
        for durable in self.messages:
            message = durable.message
            if message.message_id in message_ids or durable.enqueue_seq in enqueue_seqs:
                raise ValueError("message ids and enqueue_seq values must be unique")
            message_ids.add(message.message_id)
            enqueue_seqs.add(durable.enqueue_seq)
            if message.sender_id not in known_agents or message.recipient_id not in known_agents:
                raise ValueError("durable message references an unknown mailbox agent")
            try:
                json.dumps(message.payload, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError("durable message payload must be JSON-safe") from exc
        if not message_ids <= self.seen_message_ids:
            raise ValueError("all durable messages must be present in dedupe state")
        return self
