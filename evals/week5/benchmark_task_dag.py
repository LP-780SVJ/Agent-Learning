from __future__ import annotations

import platform
import random
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from codeteam.agent_team.dag import TaskDAG, TaskNode
from codeteam.agent_team.models import AgentRole, WorkerAssignment

SEED = 20260825
SIZES = (100, 500, 1000)
SHAPES = ("chain", "wide", "layered", "disconnected")
WARMUP_RUNS = 5
MEASURED_RUNS = 30
OUTPUT_PATH = Path("docs/benchmark/W5_DAG_BENCHMARK.md")


def assignment(node_id: str) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=node_id,
        task_id="benchmark-task",
        source_step_id=f"step-{node_id}",
        role=AgentRole.GENERAL,
        goal=f"Benchmark node {node_id}",
        expected_output=f"{node_id} complete",
    )


def node_id(index: int) -> str:
    return f"N{index:04d}"


def build_dag(node_count: int, edges: Iterable[tuple[str, str]]) -> TaskDAG:
    dag = TaskDAG()
    for index in range(node_count):
        current_id = node_id(index)
        dag.add_task(TaskNode(node_id=current_id, assignment=assignment(current_id)))
    for prerequisite_id, dependent_id in edges:
        dag.add_dependency(prerequisite_id, dependent_id)
    return dag


def chain_edges(node_count: int) -> tuple[tuple[str, str], ...]:
    return tuple(
        (node_id(index), node_id(index + 1)) for index in range(node_count - 1)
    )


def wide_edges(node_count: int) -> tuple[tuple[str, str], ...]:
    if node_count < 3:
        return chain_edges(node_count)
    root = node_id(0)
    sink = node_id(node_count - 1)
    edges: list[tuple[str, str]] = []
    for index in range(1, node_count - 1):
        middle = node_id(index)
        edges.append((root, middle))
        edges.append((middle, sink))
    return tuple(edges)


def layered_edges(node_count: int) -> tuple[tuple[str, str], ...]:
    rng = random.Random(SEED + node_count)
    layer_count = 10
    layers: list[list[int]] = [[] for _ in range(layer_count)]
    for index in range(node_count):
        layers[index * layer_count // node_count].append(index)

    edges: set[tuple[str, str]] = set()
    for layer_index in range(layer_count - 1):
        current_layer = layers[layer_index]
        next_layer = layers[layer_index + 1]
        next_width = len(next_layer)
        for position, current in enumerate(current_layer):
            first = next_layer[position % next_width]
            second = next_layer[(position + rng.randrange(next_width)) % next_width]
            edges.add((node_id(current), node_id(first)))
            edges.add((node_id(current), node_id(second)))
    return tuple(sorted(edges))


def disconnected_edges(node_count: int) -> tuple[tuple[str, str], ...]:
    component_size = 10
    edges: list[tuple[str, str]] = []
    for start in range(0, node_count, component_size):
        end = min(start + component_size, node_count)
        for index in range(start, end - 1):
            edges.append((node_id(index), node_id(index + 1)))
    return tuple(edges)


def make_edges(shape: str, node_count: int) -> tuple[tuple[str, str], ...]:
    if shape == "chain":
        return chain_edges(node_count)
    if shape == "wide":
        return wide_edges(node_count)
    if shape == "layered":
        return layered_edges(node_count)
    if shape == "disconnected":
        return disconnected_edges(node_count)
    raise ValueError(f"unknown shape: {shape}")


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = int(0.95 * (len(ordered) - 1))
    return ordered[index]


def measure(operation: Callable[[], object]) -> tuple[float, float]:
    values: list[float] = []
    for run_index in range(WARMUP_RUNS + MEASURED_RUNS):
        start = time.perf_counter_ns()
        operation()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        if run_index >= WARMUP_RUNS:
            values.append(elapsed_ms)
    return median(values), p95(values)


def commit_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def benchmark_case(
    shape: str,
    node_count: int,
) -> dict[str, object]:
    edges = make_edges(shape, node_count)
    base_dag = build_dag(node_count, edges)

    build_median, build_p95 = measure(lambda: build_dag(node_count, edges))
    validate_median, validate_p95 = measure(base_dag.validate)
    topo_median, topo_p95 = measure(base_dag.topological_sort)
    ready_median, ready_p95 = measure(base_dag.get_ready_tasks)

    return {
        "shape": shape,
        "node_count": node_count,
        "edge_count": len(edges),
        "build_median_ms": build_median,
        "build_p95_ms": build_p95,
        "validate_median_ms": validate_median,
        "validate_p95_ms": validate_p95,
        "topological_sort_median_ms": topo_median,
        "topological_sort_p95_ms": topo_p95,
        "get_ready_tasks_median_ms": ready_median,
        "get_ready_tasks_p95_ms": ready_p95,
    }


def format_float(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_report(rows: list[dict[str, object]]) -> None:
    python_version = platform.python_version()
    implementation = platform.python_implementation()
    sha = commit_sha()
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")

    lines = [
        "# W5 DAG Benchmark",
        "",
        "## Scope",
        "",
        (
            "This benchmark measures in-memory `TaskDAG` operations only: build, "
            "validate, topological sort, and ready-task query. It does not "
            "measure Scheduler throughput, Worker execution, mailbox behavior, "
            "or Multi-Agent speedup."
        ),
        "",
        "## Environment",
        "",
        f"- Generated at: {generated_at}",
        f"- Commit SHA: `{sha}`",
        f"- Python: `{implementation} {python_version}`",
        f"- Random seed: `{SEED}`",
        f"- Warmup runs per case: `{WARMUP_RUNS}`",
        f"- Measured runs per case: `{MEASURED_RUNS}`",
        "",
        "## Results",
        "",
        (
            "| shape | nodes | edges | build median ms | build p95 ms | "
            "validate median ms | validate p95 ms | topo median ms | "
            "topo p95 ms | ready median ms | ready p95 ms |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {shape} | {node_count} | {edge_count} | {build_median_ms} | "
            "{build_p95_ms} | {validate_median_ms} | {validate_p95_ms} | "
            "{topological_sort_median_ms} | {topological_sort_p95_ms} | "
            "{get_ready_tasks_median_ms} | {get_ready_tasks_p95_ms} |".format(
                **{key: format_float(value) for key, value in row.items()}
            )
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- These numbers show the local cost of deterministic DAG operations.",
            "- They do not prove that multiple agents are faster or better.",
            (
                "- Snapshot copying is included in `topological_sort()` and "
                "`get_ready_tasks()` because public node references are "
                "defensive copies."
            ),
            (
                "- Deterministic Kahn sorting uses a heap, so the expected "
                "complexity is `O((V + E) log V)` rather than strict `O(V + E)`."
            ),
            "",
            "## Ablation Status",
            "",
            (
                "- Remove dependency graph: DEFERRED / NOT_RUN. Requires Day3 "
                "Scheduler metrics to measure wrong parallelism or serialization."
            ),
            (
                "- Remove cycle detection: DEFERRED / NOT_RUN. Requires "
                "Scheduler deadlock/no-ready metrics."
            ),
            (
                "- Ignore failed dependencies: DEFERRED / NOT_RUN. Requires "
                "Day3 failure propagation behavior."
            ),
        ]
    )
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    random.seed(SEED)
    rows: list[dict[str, object]] = []
    for node_count in SIZES:
        for shape in SHAPES:
            row = benchmark_case(shape, node_count)
            rows.append(row)
            print(
                f"{shape:12} nodes={node_count:4} edges={row['edge_count']:4} "
                f"topo_median_ms={row['topological_sort_median_ms']:.3f}"
            )
    write_report(rows)
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
