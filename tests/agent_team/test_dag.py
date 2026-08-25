from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeteam.agent_team import (
    InvalidTaskStatusError as ExportedInvalidTaskStatusError,
)
from codeteam.agent_team import (
    TaskDAG as ExportedTaskDAG,
)
from codeteam.agent_team import (
    UndeclaredDependenciesError as ExportedUndeclaredDependenciesError,
)
from codeteam.agent_team.dag import (
    CycleDetectedError,
    DuplicateTaskNodeError,
    InvalidDependencyError,
    InvalidTaskStatusError,
    TaskDAG,
    TaskNode,
    TaskStatus,
    UndeclaredDependenciesError,
    UnknownTaskNodeError,
)
from codeteam.agent_team.models import AgentRole, LeadPlanningResult, WorkerAssignment
from codeteam.planning.models import PlanStep, create_plan


def _assignment(
    assignment_id: str,
    *,
    step_id: str | None = None,
) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=assignment_id,
        task_id="task-1",
        source_step_id=step_id or assignment_id,
        role=AgentRole.BACKEND,
        goal=f"Complete {assignment_id}",
        expected_output=f"{assignment_id} done",
    )


def _node(node_id: str, *, status: TaskStatus = TaskStatus.PENDING) -> TaskNode:
    return TaskNode(
        node_id=node_id,
        assignment=_assignment(node_id),
        status=status,
    )


def _dag(*node_ids: str) -> TaskDAG:
    dag = TaskDAG()
    for node_id in node_ids:
        dag.add_task(_node(node_id))
    return dag


def _ids(nodes: tuple[TaskNode, ...]) -> tuple[str, ...]:
    return tuple(node.node_id for node in nodes)


def _snapshot(dag: TaskDAG) -> tuple[tuple[str, ...], dict[str, frozenset[str]]]:
    return _ids(dag.nodes), dag.dependencies


def _set_status(dag: TaskDAG, node_id: str, status: TaskStatus) -> None:
    dag.replace_task_status(node_id, status)


def test_task_node_can_be_constructed() -> None:
    node = _node("A")

    assert node.node_id == "A"
    assert node.status is TaskStatus.PENDING


def test_task_node_rejects_blank_node_id() -> None:
    with pytest.raises(ValidationError, match="node_id"):
        TaskNode(node_id="   ", assignment=_assignment("A"))


def test_task_node_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        TaskNode(node_id="A", assignment=_assignment("A"), status="waiting")


def test_add_task_initializes_node_and_empty_dependencies() -> None:
    dag = _dag("B", "A")

    assert _ids(dag.nodes) == ("A", "B")
    assert dag.dependencies == {"A": frozenset(), "B": frozenset()}


def test_add_task_rejects_duplicate_node_id() -> None:
    dag = _dag("A")

    with pytest.raises(DuplicateTaskNodeError, match="A"):
        dag.add_task(_node("A"))


def test_add_task_defensively_copies_input_node() -> None:
    node = _node("A")
    dag = TaskDAG()

    dag.add_task(node)
    node.node_id = "Z"
    node.status = "corrupted"  # type: ignore[assignment]

    assert _ids(dag.nodes) == ("A",)
    assert dag.nodes[0].status is TaskStatus.PENDING


def test_add_dependency_direction_is_prerequisite_to_dependent() -> None:
    dag = _dag("A", "B")

    dag.add_dependency("A", "B")

    assert dag.dependencies["B"] == frozenset({"A"})
    assert dag.dependencies["A"] == frozenset()


def test_add_dependency_rejects_unknown_prerequisite() -> None:
    dag = _dag("B")

    with pytest.raises(UnknownTaskNodeError, match="A"):
        dag.add_dependency("A", "B")


def test_add_dependency_rejects_unknown_dependent() -> None:
    dag = _dag("A")

    with pytest.raises(UnknownTaskNodeError, match="B"):
        dag.add_dependency("A", "B")


def test_add_dependency_rejects_self_dependency() -> None:
    dag = _dag("A")

    with pytest.raises(InvalidDependencyError, match="itself"):
        dag.add_dependency("A", "A")


def test_duplicate_edge_is_idempotent() -> None:
    dag = _dag("A", "B")

    dag.add_dependency("A", "B")
    dag.add_dependency("A", "B")

    assert dag.dependencies["B"] == frozenset({"A"})


def test_chain_topological_sort() -> None:
    dag = _dag("A", "B", "C")
    dag.add_dependency("A", "B")
    dag.add_dependency("B", "C")

    assert _ids(dag.topological_sort()) == ("A", "B", "C")


def test_diamond_topological_sort_respects_all_edges() -> None:
    dag = _dag("A", "B", "C", "D")
    dag.add_dependency("A", "B")
    dag.add_dependency("A", "C")
    dag.add_dependency("B", "D")
    dag.add_dependency("C", "D")

    order = _ids(dag.topological_sort())
    positions = {node_id: index for index, node_id in enumerate(order)}

    assert order == ("A", "B", "C", "D")
    assert positions["A"] < positions["B"]
    assert positions["A"] < positions["C"]
    assert positions["B"] < positions["D"]
    assert positions["C"] < positions["D"]


def test_fan_out_and_fan_in_ready_flow() -> None:
    dag = _dag("A", "B", "C", "D")
    dag.add_dependency("A", "B")
    dag.add_dependency("A", "C")
    dag.add_dependency("B", "D")
    dag.add_dependency("C", "D")

    assert _ids(dag.get_ready_tasks()) == ("A",)

    _set_status(dag, "A", TaskStatus.COMPLETED)
    assert _ids(dag.get_ready_tasks()) == ("B", "C")

    _set_status(dag, "B", TaskStatus.COMPLETED)
    assert _ids(dag.get_ready_tasks()) == ("C",)

    _set_status(dag, "C", TaskStatus.COMPLETED)
    assert _ids(dag.get_ready_tasks()) == ("D",)


def test_each_non_pending_status_is_not_returned_as_ready() -> None:
    for status in (
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.BLOCKED,
    ):
        dag = _dag("A")
        _set_status(dag, "A", status)

        assert dag.get_ready_tasks() == ()


def test_parallel_root_nodes_have_stable_ready_order() -> None:
    dag = _dag("C", "A", "B")

    assert _ids(dag.get_ready_tasks()) == ("A", "B", "C")


def test_disconnected_subgraphs_sort_stably() -> None:
    dag = _dag("A", "B", "C", "D")
    dag.add_dependency("A", "B")
    dag.add_dependency("C", "D")

    assert _ids(dag.topological_sort()) == ("A", "B", "C", "D")


def test_partial_completion_makes_dependent_ready() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    _set_status(dag, "A", TaskStatus.COMPLETED)

    assert _ids(dag.get_ready_tasks()) == ("B",)


def test_all_completed_returns_no_ready_tasks() -> None:
    dag = _dag("A", "B")
    _set_status(dag, "A", TaskStatus.COMPLETED)
    _set_status(dag, "B", TaskStatus.COMPLETED)

    assert dag.get_ready_tasks() == ()


def test_failed_prerequisite_keeps_dependent_not_ready_without_status_change() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    _set_status(dag, "A", TaskStatus.FAILED)
    before = dag.nodes[1].status

    assert dag.get_ready_tasks() == ()
    assert dag.nodes[1].status is before


def test_replace_task_status_rejects_bare_string_without_polluting_dag() -> None:
    dag = _dag("A")

    with pytest.raises(InvalidTaskStatusError, match="TaskStatus"):
        dag.replace_task_status("A", "completed")  # type: ignore[arg-type]

    assert dag.nodes[0].status is TaskStatus.PENDING


def test_validate_rejects_two_node_cycle() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    dag.add_dependency("B", "A")

    with pytest.raises(CycleDetectedError):
        dag.validate()


def test_topological_sort_rejects_long_cycle() -> None:
    dag = _dag("A", "B", "C")
    dag.add_dependency("A", "B")
    dag.add_dependency("B", "C")
    dag.add_dependency("C", "A")

    with pytest.raises(CycleDetectedError):
        dag.topological_sort()


def test_topological_sort_is_stable() -> None:
    dag = _dag("A", "B", "C", "D")
    dag.add_dependency("A", "D")
    dag.add_dependency("B", "D")

    first = _ids(dag.topological_sort())
    second = _ids(dag.topological_sort())

    assert first == second


def test_topological_result_satisfies_all_edges() -> None:
    dag = _dag("A", "B", "C", "D", "E")
    edges = (("A", "C"), ("B", "C"), ("C", "E"), ("D", "E"))
    for prerequisite, dependent in edges:
        dag.add_dependency(prerequisite, dependent)

    order = _ids(dag.topological_sort())
    positions = {node_id: index for index, node_id in enumerate(order)}

    for prerequisite, dependent in edges:
        assert positions[prerequisite] < positions[dependent]


def test_validate_has_no_side_effects() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    before = _snapshot(dag)

    dag.validate()

    assert _snapshot(dag) == before


def test_topological_sort_has_no_side_effects() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    before = _snapshot(dag)

    dag.topological_sort()

    assert _snapshot(dag) == before


def test_get_ready_tasks_has_no_side_effects() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    before = (
        _snapshot(dag),
        {node.node_id: node.status for node in dag.nodes},
    )

    dag.get_ready_tasks()

    after = (
        _snapshot(dag),
        {node.node_id: node.status for node in dag.nodes},
    )
    assert after == before


def test_nodes_snapshot_mutation_does_not_affect_dag() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    node = dag.nodes[0]

    node.node_id = "Z"
    node.status = "corrupted"  # type: ignore[assignment]

    assert _ids(dag.nodes) == ("A", "B")
    assert dag.nodes[0].status is TaskStatus.PENDING
    assert dag.dependencies["B"] == frozenset({"A"})


def test_topological_sort_snapshot_mutation_does_not_affect_dag() -> None:
    dag = _dag("A", "B")
    dag.add_dependency("A", "B")
    node = dag.topological_sort()[0]

    node.node_id = "Z"
    node.status = "corrupted"  # type: ignore[assignment]

    assert _ids(dag.topological_sort()) == ("A", "B")
    assert dag.topological_sort()[0].status is TaskStatus.PENDING


def test_get_ready_tasks_snapshot_mutation_does_not_affect_dag() -> None:
    dag = _dag("A", "B")
    ready_node = dag.get_ready_tasks()[0]

    ready_node.node_id = "Z"
    ready_node.status = "corrupted"  # type: ignore[assignment]

    assert _ids(dag.get_ready_tasks()) == ("A", "B")
    assert dag.get_ready_tasks()[0].status is TaskStatus.PENDING


def test_dependencies_snapshot_does_not_expose_internal_sets() -> None:
    dag = _dag("A", "B")
    snapshot = dag.dependencies

    with pytest.raises(AttributeError):
        snapshot["B"].add("A")  # type: ignore[attr-defined]

    assert dag.dependencies["B"] == frozenset()


def test_from_lead_planning_result_builds_nodes_and_explicit_dependencies() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(
            PlanStep(step_id="P1", title="Backend", description="Backend"),
            PlanStep(step_id="P2", title="Frontend", description="Frontend"),
            PlanStep(step_id="P3", title="Tests", description="Tests"),
        ),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(
            _assignment("A-backend", step_id="P1"),
            _assignment("A-frontend", step_id="P2"),
            _assignment("A-tests", step_id="P3"),
        ),
    )

    dag = TaskDAG.from_lead_planning_result(
        result,
        dependencies=(
            ("A-backend", "A-tests"),
            ("A-frontend", "A-tests"),
        ),
    )

    assert _ids(dag.nodes) == ("A-backend", "A-frontend", "A-tests")
    assert dag.dependencies["A-tests"] == frozenset({"A-backend", "A-frontend"})
    assert _ids(dag.get_ready_tasks()) == ("A-backend", "A-frontend")


def test_from_lead_planning_result_rejects_undeclared_multi_node_dependencies() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(
            PlanStep(step_id="P1", title="First", description="First"),
            PlanStep(step_id="P2", title="Second", description="Second"),
        ),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(
            _assignment("A-first", step_id="P1"),
            _assignment("A-second", step_id="P2"),
        ),
    )

    with pytest.raises(UndeclaredDependenciesError, match="dependencies"):
        TaskDAG.from_lead_planning_result(result)


def test_from_lead_planning_result_allows_single_node_without_dependencies() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(PlanStep(step_id="P1", title="Only", description="Only"),),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(_assignment("A-only", step_id="P1"),),
    )

    dag = TaskDAG.from_lead_planning_result(result)

    assert _ids(dag.nodes) == ("A-only",)
    assert _ids(dag.get_ready_tasks()) == ("A-only",)


def test_from_lead_planning_result_empty_dependencies_means_independent() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(
            PlanStep(step_id="P1", title="First", description="First"),
            PlanStep(step_id="P2", title="Second", description="Second"),
        ),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(
            _assignment("A-first", step_id="P1"),
            _assignment("A-second", step_id="P2"),
        ),
    )

    dag = TaskDAG.from_lead_planning_result(result, dependencies=())

    assert dag.dependencies == {
        "A-first": frozenset(),
        "A-second": frozenset(),
    }
    assert _ids(dag.get_ready_tasks()) == ("A-first", "A-second")


def test_from_lead_planning_result_rejects_unknown_dependency_endpoint() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(PlanStep(step_id="P1", title="Only", description="Only"),),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(_assignment("A-only", step_id="P1"),),
    )

    with pytest.raises(UnknownTaskNodeError, match="missing"):
        TaskDAG.from_lead_planning_result(
            result,
            dependencies=(("missing", "A-only"),),
        )


def test_from_lead_planning_result_rejects_self_dependency() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(PlanStep(step_id="P1", title="Only", description="Only"),),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(_assignment("A-only", step_id="P1"),),
    )

    with pytest.raises(InvalidDependencyError, match="itself"):
        TaskDAG.from_lead_planning_result(
            result,
            dependencies=(("A-only", "A-only"),),
        )


def test_from_lead_planning_result_duplicate_dependency_is_idempotent() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(
            PlanStep(step_id="P1", title="First", description="First"),
            PlanStep(step_id="P2", title="Second", description="Second"),
        ),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(
            _assignment("A-first", step_id="P1"),
            _assignment("A-second", step_id="P2"),
        ),
    )

    dag = TaskDAG.from_lead_planning_result(
        result,
        dependencies=(("A-first", "A-second"), ("A-first", "A-second")),
    )

    assert dag.dependencies["A-second"] == frozenset({"A-first"})


def test_from_lead_planning_result_rejects_cycle() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(
            PlanStep(step_id="P1", title="First", description="First"),
            PlanStep(step_id="P2", title="Second", description="Second"),
        ),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(
            _assignment("A-first", step_id="P1"),
            _assignment("A-second", step_id="P2"),
        ),
    )

    with pytest.raises(CycleDetectedError):
        TaskDAG.from_lead_planning_result(
            result,
            dependencies=(("A-first", "A-second"), ("A-second", "A-first")),
        )


def test_dependency_pairs_use_node_id_not_source_step_id() -> None:
    plan = create_plan(
        plan_id="plan-1",
        task_id="task-1",
        steps=(
            PlanStep(step_id="P1", title="Backend", description="Backend"),
            PlanStep(step_id="P2", title="Tests", description="Tests"),
        ),
    )
    result = LeadPlanningResult(
        task_id="task-1",
        plan=plan,
        assignments=(
            _assignment("A-backend", step_id="P1"),
            _assignment("A-tests", step_id="P2"),
        ),
    )

    with pytest.raises(UnknownTaskNodeError, match="P1"):
        TaskDAG.from_lead_planning_result(
            result,
            dependencies=(("P1", "P2"),),
        )

    dag = TaskDAG.from_lead_planning_result(
        result,
        dependencies=(("A-backend", "A-tests"),),
    )
    assert dag.dependencies["A-tests"] == frozenset({"A-backend"})


def test_heap_topological_sort_is_stable_and_respects_edges() -> None:
    dag = _dag("N4", "N1", "N3", "N2", "N5", "N6")
    edges = (
        ("N1", "N4"),
        ("N2", "N4"),
        ("N2", "N5"),
        ("N3", "N5"),
        ("N4", "N6"),
        ("N5", "N6"),
    )
    for prerequisite, dependent in edges:
        dag.add_dependency(prerequisite, dependent)

    first = _ids(dag.topological_sort())
    second = _ids(dag.topological_sort())
    positions = {node_id: index for index, node_id in enumerate(first)}

    assert first == second
    assert first == ("N1", "N2", "N3", "N4", "N5", "N6")
    for prerequisite, dependent in edges:
        assert positions[prerequisite] < positions[dependent]


def test_public_api_exports_task_dag() -> None:
    assert ExportedTaskDAG is TaskDAG
    assert ExportedInvalidTaskStatusError is InvalidTaskStatusError
    assert ExportedUndeclaredDependenciesError is UndeclaredDependenciesError
