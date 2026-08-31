from __future__ import annotations

import platform
import random
import subprocess
import sys
import time
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from statistics import median
from threading import Barrier, Thread
from typing import TypeVar

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from codeteam.agent_team.dag import TaskDAG, TaskNode
from codeteam.agent_team.models import (
    AgentIdentity,
    AgentInfo,
    AgentRole,
    AgentStatus,
    WorkerAssignment,
)
from codeteam.agent_team.scheduler import TaskClaim, TaskScheduler
from codeteam.agent_team.worker import WorkerAgent, WorkerRegistry

SEED = 20260826
TASK_COUNTS = (100, 500, 1000)
WORKER_COUNTS = (1, 4, 8, 16)
WARMUP_RUNS = 5
MEASURED_RUNS = 30
JOIN_TIMEOUT_SECONDS = 2.0
OUTPUT_PATH = REPO_ROOT / "docs/benchmark/W5_SCHEDULER.md"
T = TypeVar("T")


def node_id(index: int) -> str:
    return f"N{index:04d}"


def worker_id(index: int) -> str:
    return f"worker-{index:02d}"


def assignment(current_node_id: str) -> WorkerAssignment:
    return WorkerAssignment(
        assignment_id=current_node_id,
        task_id="scheduler-benchmark",
        source_step_id=f"step-{current_node_id}",
        role=AgentRole.BACKEND,
        goal=f"Benchmark {current_node_id}",
        expected_output=f"{current_node_id} complete",
    )


def build_dag(task_count: int) -> TaskDAG:
    dag = TaskDAG()
    for index in range(task_count):
        current_node_id = node_id(index)
        dag.add_task(
            TaskNode(
                node_id=current_node_id,
                assignment=assignment(current_node_id),
            )
        )
    return dag


def worker(current_worker_id: str) -> WorkerAgent:
    return WorkerAgent(
        AgentInfo(
            identity=AgentIdentity(
                agent_id=current_worker_id,
                display_name=current_worker_id,
            ),
            role=AgentRole.BACKEND,
            status=AgentStatus.READY,
        )
    )


def build_registry(worker_count: int) -> WorkerRegistry:
    registry = WorkerRegistry()
    for index in range(worker_count):
        registry.register(worker(worker_id(index)))
    return registry


def build_scheduler(task_count: int, worker_count: int) -> TaskScheduler:
    return TaskScheduler(build_dag(task_count), build_registry(worker_count))


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = int(0.95 * (len(ordered) - 1))
    return ordered[index]


def measure_ms(operation: Callable[[], object]) -> tuple[float, float]:
    values: list[float] = []
    for run_index in range(WARMUP_RUNS + MEASURED_RUNS):
        start = time.perf_counter_ns()
        operation()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        if run_index >= WARMUP_RUNS:
            values.append(elapsed_ms)
    return median(values), p95(values)


def measure_ms_with_setup(
    setup: Callable[[], T],
    operation: Callable[[T], object],
) -> tuple[float, float]:
    values: list[float] = []
    for run_index in range(WARMUP_RUNS + MEASURED_RUNS):
        subject = setup()
        start = time.perf_counter_ns()
        operation(subject)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        if run_index >= WARMUP_RUNS:
            values.append(elapsed_ms)
    return median(values), p95(values)


def measure_values(operation: Callable[[], float]) -> tuple[float, float]:
    values: list[float] = []
    for run_index in range(WARMUP_RUNS + MEASURED_RUNS):
        value = operation()
        if run_index >= WARMUP_RUNS:
            values.append(value)
    return median(values), p95(values)


def claim_throughput(task_count: int, worker_count: int) -> float:
    scheduler = build_scheduler(task_count, worker_count)
    scheduler.schedule()
    start = time.perf_counter_ns()
    claim_count = 0
    for index in range(worker_count):
        claim = scheduler.claim(scheduler.registry.lease(worker_id(index)))
        if claim is not None:
            claim_count += 1
    elapsed_seconds = (time.perf_counter_ns() - start) / 1_000_000_000
    if elapsed_seconds == 0:
        return float("inf")
    return claim_count / elapsed_seconds


def contention_failure_rate(worker_count: int) -> float:
    scheduler = build_scheduler(task_count=1, worker_count=worker_count)
    scheduler.schedule()
    barrier = Barrier(worker_count)
    claims: list[TaskClaim | None] = []
    errors: list[BaseException] = []

    def contender(index: int) -> None:
        try:
            barrier.wait()
            claims.append(scheduler.claim(scheduler.registry.lease(worker_id(index))))
        except RuntimeError as exc:
            errors.append(exc)

    threads = [Thread(target=contender, args=(index,)) for index in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT_SECONDS)
    live_threads = [thread.name for thread in threads if thread.is_alive()]
    if live_threads:
        raise RuntimeError(f"benchmark contention threads did not finish: {live_threads}")

    successes = len([claim for claim in claims if claim is not None])
    failures = worker_count - successes + len(errors)
    return failures / worker_count


def commit_sha() -> str:
    return git_output(["git", "rev-parse", "--short", "HEAD"])


def base_head() -> str:
    return git_output(["git", "rev-parse", "HEAD"])


def git_output(argv: list[str]) -> str:
    try:
        result = subprocess.run(
            argv,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def working_tree_state() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return "dirty" if result.stdout.strip() else "clean"


def file_sha256(relative_path: str) -> str:
    return sha256((REPO_ROOT / relative_path).read_bytes()).hexdigest()


def benchmark_case(task_count: int, worker_count: int) -> dict[str, object]:
    setup_median, setup_p95 = measure_ms(
        lambda: build_scheduler(task_count, worker_count)
    )
    schedule_median, schedule_p95 = measure_ms_with_setup(
        lambda: build_scheduler(task_count, worker_count),
        lambda scheduler: scheduler.schedule(),
    )
    throughput_median, throughput_p95 = measure_values(
        lambda: claim_throughput(task_count, worker_count)
    )
    contention_median, contention_p95 = measure_values(
        lambda: contention_failure_rate(worker_count)
    )
    return {
        "task_count": task_count,
        "worker_count": worker_count,
        "scheduler_setup_median_ms": setup_median,
        "scheduler_setup_p95_ms": setup_p95,
        "schedule_median_ms": schedule_median,
        "schedule_p95_ms": schedule_p95,
        "claim_throughput_median_ops_s": throughput_median,
        "claim_throughput_p95_ops_s": throughput_p95,
        "contention_failure_rate_median": contention_median,
        "contention_failure_rate_p95": contention_p95,
    }


def format_float(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_report(rows: list[dict[str, object]]) -> None:
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "# W5 Scheduler Benchmark",
        "",
        "## Scope",
        "",
        (
            "This benchmark measures the in-process synchronous TaskScheduler "
            "only. It covers schedule latency, first-wave claim throughput, and "
            "duplicate-claim contention failure rate. It does not measure "
            "Worker execution, mailbox behavior, crash recovery, durable queue "
            "replay, or Multi-Agent speedup."
        ),
        "",
        "## Environment",
        "",
        f"- Generated at: {generated_at}",
        f"- Base HEAD: `{base_head()}`",
        f"- Commit SHA: `{commit_sha()}`",
        f"- Working tree: `{working_tree_state()}`",
        f"- scheduler.py SHA-256: `{file_sha256('codeteam/agent_team/scheduler.py')}`",
        (
            "- benchmark_scheduler.py SHA-256: "
            f"`{file_sha256('evals/week5/benchmark_scheduler.py')}`"
        ),
        f"- Python: `{platform.python_implementation()} {platform.python_version()}`",
        f"- Random seed: `{SEED}`",
        f"- Warmup runs per case: `{WARMUP_RUNS}`",
        f"- Measured runs per case: `{MEASURED_RUNS}`",
        "",
        "## Results",
        "",
        (
            "| tasks | workers | setup median ms | setup p95 ms | "
            "schedule median ms | schedule p95 ms | claim throughput median ops/s | "
            "claim throughput p95 ops/s | contention failure median | "
            "contention failure p95 |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        formatted = {key: format_float(value) for key, value in row.items()}
        lines.append(
            "| {task_count} | {worker_count} | {scheduler_setup_median_ms} | "
            "{scheduler_setup_p95_ms} | {schedule_median_ms} | "
            "{schedule_p95_ms} | {claim_throughput_median_ops_s} | "
            "{claim_throughput_p95_ops_s} | {contention_failure_rate_median} | "
            "{contention_failure_rate_p95} |".format(**formatted)
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "- Schedule latency includes dependency-ready resolution and "
                "idempotent enqueue for independent tasks. Scheduler/DAG/Registry "
                "setup is reported separately."
            ),
            (
                "- Claim throughput measures only the first wave of in-process "
                "claims; it does not include Worker execution."
            ),
            (
                "- Contention failure rate is expected to approach `(workers - 1) "
                "/ workers` for one task because exactly one worker should win."
            ),
            "- These results do not prove end-to-end Multi-Agent acceleration.",
            "",
            "## Deferred Metrics",
            "",
            (
                "- Recovery latency: DEFERRED / NOT_RUN until Day5 crash and "
                "heartbeat semantics exist."
            ),
            (
                "- Durable replay latency: DEFERRED / NOT_RUN until Day6 TaskStore "
                "exists."
            ),
            (
                "- End-to-end task success/cost/latency: DEFERRED / NOT_RUN until "
                "Worker execution and merge/review are connected."
            ),
        ]
    )
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    random.seed(SEED)
    rows: list[dict[str, object]] = []
    for task_count in TASK_COUNTS:
        for worker_count in WORKER_COUNTS:
            row = benchmark_case(task_count, worker_count)
            rows.append(row)
            print(
                f"tasks={task_count:4} workers={worker_count:2} "
                f"setup_ms={row['scheduler_setup_median_ms']:.3f} "
                f"schedule_ms={row['schedule_median_ms']:.3f} "
                f"claim_ops_s={row['claim_throughput_median_ops_s']:.1f}"
            )
    write_report(rows)
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
