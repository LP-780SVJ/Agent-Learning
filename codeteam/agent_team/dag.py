from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, field_validator

from codeteam.agent_team.models import LeadPlanningResult, WorkerAssignment


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskNode(BaseModel):
    node_id: str
    assignment: WorkerAssignment
    status: TaskStatus = TaskStatus.PENDING

    @field_validator("node_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("node_id must not be blank")
        return stripped


class DAGError(Exception):
    """Base class for Task DAG domain errors."""


class DuplicateTaskNodeError(DAGError):
    """Raised when a node id is added more than once."""


class UnknownTaskNodeError(DAGError):
    """Raised when a dependency references an unknown node id."""


class InvalidDependencyError(DAGError):
    """Raised when a dependency is malformed."""


class CycleDetectedError(DAGError):
    """Raised when the graph is not acyclic."""


class TaskDAG:
    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}
        self._dependencies: dict[str, set[str]] = {}

    @classmethod
    def from_lead_planning_result(
        cls,
        result: LeadPlanningResult,
        *,
        dependencies: tuple[tuple[str, str], ...] = (),
    ) -> TaskDAG:
        dag = cls()
        for assignment in result.assignments:
            dag.add_task(
                TaskNode(
                    node_id=assignment.assignment_id,
                    assignment=assignment,
                )
            )
        for prerequisite_id, dependent_id in dependencies:
            dag.add_dependency(prerequisite_id, dependent_id)
        return dag

    @property
    def nodes(self) -> tuple[TaskNode, ...]:
        return tuple(self._nodes[node_id] for node_id in sorted(self._nodes))

    @property
    def dependencies(self) -> dict[str, frozenset[str]]:
        return {
            node_id: frozenset(self._dependencies[node_id])
            for node_id in sorted(self._dependencies)
        }

    def add_task(self, node: TaskNode) -> None:
        if node.node_id in self._nodes:
            raise DuplicateTaskNodeError(node.node_id)
        self._nodes[node.node_id] = node
        self._dependencies[node.node_id] = set()

    def add_dependency(self, prerequisite_id: str, dependent_id: str) -> None:
        if prerequisite_id == dependent_id:
            raise InvalidDependencyError("A task cannot depend on itself")
        self._require_node(prerequisite_id)
        self._require_node(dependent_id)
        self._dependencies[dependent_id].add(prerequisite_id)

    def validate(self) -> None:
        for dependent_id, prerequisite_ids in self._dependencies.items():
            self._require_node(dependent_id)
            for prerequisite_id in prerequisite_ids:
                if prerequisite_id == dependent_id:
                    raise InvalidDependencyError(
                        "A task cannot depend on itself"
                    )
                self._require_node(prerequisite_id)
        self.topological_sort()

    def topological_sort(self) -> tuple[TaskNode, ...]:
        indegrees = {
            node_id: len(prerequisites)
            for node_id, prerequisites in self._dependencies.items()
        }
        dependents = self._dependents()
        ready = sorted(
            node_id
            for node_id, indegree in indegrees.items()
            if indegree == 0
        )
        ordered_ids: list[str] = []

        while ready:
            node_id = ready.pop(0)
            ordered_ids.append(node_id)

            for dependent_id in sorted(dependents[node_id]):
                indegrees[dependent_id] -= 1
                if indegrees[dependent_id] == 0:
                    ready.append(dependent_id)
            ready.sort()

        if len(ordered_ids) != len(self._nodes):
            raise CycleDetectedError("Task DAG contains a cycle")

        return tuple(self._nodes[node_id] for node_id in ordered_ids)

    def get_ready_tasks(self) -> tuple[TaskNode, ...]:
        ready: list[TaskNode] = []
        for node_id in sorted(self._nodes):
            node = self._nodes[node_id]
            if node.status is not TaskStatus.PENDING:
                continue
            prerequisites = self._dependencies[node_id]
            if all(
                self._nodes[prerequisite_id].status is TaskStatus.COMPLETED
                for prerequisite_id in prerequisites
            ):
                ready.append(node)
        return tuple(ready)

    def _require_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise UnknownTaskNodeError(node_id)

    def _dependents(self) -> dict[str, set[str]]:
        dependents = {node_id: set() for node_id in self._nodes}
        for dependent_id, prerequisite_ids in self._dependencies.items():
            for prerequisite_id in prerequisite_ids:
                self._require_node(prerequisite_id)
                dependents[prerequisite_id].add(dependent_id)
        return dependents
