# W5 DAG Failure Cases

## Scope

These cases cover Week5 Day2 `TaskDAG` behavior before Day3 Scheduler work.
They are structure and query failures only; they do not claim concurrent Worker
execution or Scheduler recovery.

## F-W5-D2-01 Cycle

Reproducer:

```python
dag = TaskDAG()
dag.add_task(TaskNode(node_id="A", assignment=assignment_a))
dag.add_task(TaskNode(node_id="B", assignment=assignment_b))
dag.add_dependency("A", "B")
dag.add_dependency("B", "A")
dag.validate()
```

Expected evidence:

- `validate()` raises `CycleDetectedError`.
- `topological_sort()` also raises `CycleDetectedError`.
- The factory path validates before returning and rejects cyclic dependency
  pairs.

Why it matters:

Without cycle detection, Day3 Scheduler can enter a no-ready-but-not-complete
state and wait forever.

## F-W5-D2-02 Missing Dependency Endpoint

Reproducer:

```python
dag = TaskDAG()
dag.add_task(TaskNode(node_id="B", assignment=assignment_b))
dag.add_dependency("missing", "B")
```

Expected evidence:

- `add_dependency()` raises `UnknownTaskNodeError`.
- `from_lead_planning_result()` raises the same error for unknown node IDs.

Why it matters:

A dependency pointing to a non-existent node silently erases a required
prerequisite if it is ignored.

## F-W5-D2-03 Incorrect Dependency Direction

Reproducer:

```python
dag.add_dependency("A-tests", "A-backend")
```

when the intended order is backend before tests.

Expected evidence:

- The graph is structurally valid, so tests cannot automatically infer business
  intent from names.
- Review and future dependency planner evals must catch wrong direction.

Why it matters:

Incorrect but valid dependencies can serialize work incorrectly or run tests
before implementation. Day2 can enforce graph invariants, not semantic planning
quality.

## F-W5-D2-04 External Node Mutation

Reproducer:

```python
node = TaskNode(node_id="A", assignment=assignment_a)
dag.add_task(node)
node.node_id = "Z"
node.status = "corrupted"
```

and:

```python
snapshot = dag.nodes[0]
snapshot.node_id = "Z"
snapshot.status = "corrupted"
```

Expected evidence:

- Mutating the original node after `add_task()` does not affect the DAG.
- Mutating nodes returned by `nodes`, `topological_sort()`, or
  `get_ready_tasks()` does not affect the DAG.
- `replace_task_status("A", "completed")` rejects a bare string with
  `InvalidTaskStatusError`.

Why it matters:

Day3 Scheduler cannot rely on DAG indexes if external callers can mutate
`node_id` or bypass `TaskStatus`.

## F-W5-D2-05 Omitted Dependency Misread as Independent

Reproducer:

```python
TaskDAG.from_lead_planning_result(two_node_result)
```

Expected evidence:

- Multi-node construction with `dependencies=None` raises
  `UndeclaredDependenciesError`.
- `dependencies=()` is required to explicitly declare all nodes independent.
- Single-node construction with `dependencies=None` remains legal.

Why it matters:

If "dependency source was omitted" is treated as "all independent," Day3 can
schedule dependent work concurrently by accident.
