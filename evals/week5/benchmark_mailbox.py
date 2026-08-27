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

from codeteam.agent_team.mailbox import (
    AgentMailbox,
    AgentMessage,
    AgentMessageType,
    MailboxError,
)
from codeteam.agent_team.models import AgentIdentity

SEED = 20260826
MESSAGE_COUNTS = (100, 1000, 10000)
PRODUCER_COUNTS = (1, 4, 8)
BROADCAST_FANOUTS = (1, 4, 16, 64)
WARMUP_RUNS = 5
MEASURED_RUNS = 30
JOIN_TIMEOUT_SECONDS = 60.0
OUTPUT_PATH = REPO_ROOT / "docs/benchmark/W5_MAILBOX.md"
T = TypeVar("T")


def identity(agent_id: str) -> AgentIdentity:
    return AgentIdentity(agent_id=agent_id, display_name=agent_id)


def build_mailbox(
    *,
    producer_count: int = 1,
    recipient_count: int = 1,
    capacity_per_inbox: int = 1000,
) -> AgentMailbox:
    mailbox = AgentMailbox(capacity_per_inbox=capacity_per_inbox)
    for index in range(producer_count):
        mailbox.register_agent(identity(producer_id(index)))
    for index in range(recipient_count):
        mailbox.register_agent(identity(recipient_id(index)))
    return mailbox


def producer_id(index: int) -> str:
    return f"producer-{index:02d}"


def recipient_id(index: int) -> str:
    return f"recipient-{index:02d}"


def message(message_id: str, *, sender_id: str = "producer-00") -> AgentMessage:
    return AgentMessage(
        message_id=message_id,
        sender_id=sender_id,
        recipient_id="recipient-00",
        message_type=AgentMessageType.INFO,
        task_id="mailbox-benchmark",
        node_id="node-0001",
        correlation_id="corr-mailbox-benchmark",
        payload={
            "summary": "benchmark message",
            "index": message_id,
        },
    )


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


def send_messages(mailbox: AgentMailbox, message_count: int) -> None:
    for index in range(message_count):
        mailbox.send(message(f"msg-{index:05d}"))


def receive_messages(mailbox: AgentMailbox, message_count: int) -> None:
    for _ in range(message_count):
        if mailbox.receive("recipient-00") is None:
            raise RuntimeError("mailbox became empty before expected")


def setup_populated_mailbox(message_count: int) -> AgentMailbox:
    mailbox = build_mailbox(capacity_per_inbox=message_count + 1)
    send_messages(mailbox, message_count)
    return mailbox


def concurrent_send_throughput(message_count: int, producer_count: int) -> float:
    mailbox = build_mailbox(
        producer_count=producer_count,
        capacity_per_inbox=message_count + producer_count,
    )
    barrier = Barrier(producer_count)
    errors: list[BaseException] = []
    sent_per_producer = message_count // producer_count
    remainder = message_count % producer_count

    def producer(index: int) -> None:
        try:
            local_count = sent_per_producer + (1 if index < remainder else 0)
            barrier.wait()
            for local_index in range(local_count):
                mailbox.send(
                    message(
                        f"msg-{index:02d}-{local_index:05d}",
                        sender_id=producer_id(index),
                    )
                )
        except (RuntimeError, MailboxError) as exc:
            errors.append(exc)

    threads = [
        Thread(target=producer, args=(index,), name=f"producer-{index:02d}")
        for index in range(producer_count)
    ]
    start = time.perf_counter_ns()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT_SECONDS)
    elapsed_seconds = (time.perf_counter_ns() - start) / 1_000_000_000

    live_threads = [thread.name for thread in threads if thread.is_alive()]
    if live_threads:
        raise RuntimeError(f"mailbox benchmark threads did not finish: {live_threads}")
    if errors:
        raise RuntimeError(f"mailbox benchmark producer errors: {errors!r}")
    return message_count / elapsed_seconds


def broadcast_latency_ms(fanout: int) -> float:
    mailbox = build_mailbox(recipient_count=fanout, capacity_per_inbox=2)
    start = time.perf_counter_ns()
    mailbox.broadcast(
        sender_id="producer-00",
        recipient_ids=tuple(recipient_id(index) for index in range(fanout)),
        message_type=AgentMessageType.INFO,
        task_id="mailbox-benchmark",
        node_id="node-0001",
        payload={"summary": "broadcast benchmark"},
        correlation_id="corr-broadcast-benchmark",
    )
    return (time.perf_counter_ns() - start) / 1_000_000


def approx_backlog_bytes(message_count: int) -> int:
    sample = message("msg-sample").model_dump_json()
    return len(sample.encode("utf-8")) * message_count


def throughput_from_latency(message_count: int, elapsed_ms: float) -> float:
    if elapsed_ms == 0:
        return float("inf")
    return message_count / (elapsed_ms / 1000)


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


def benchmark_message_case(message_count: int) -> dict[str, object]:
    setup_median, setup_p95 = measure_ms(
        lambda: build_mailbox(capacity_per_inbox=message_count + 1)
    )
    send_median, send_p95 = measure_ms_with_setup(
        lambda: build_mailbox(capacity_per_inbox=message_count + 1),
        lambda mailbox: send_messages(mailbox, message_count),
    )
    receive_median, receive_p95 = measure_ms_with_setup(
        lambda: setup_populated_mailbox(message_count),
        lambda mailbox: receive_messages(mailbox, message_count),
    )
    return {
        "message_count": message_count,
        "setup_median_ms": setup_median,
        "setup_p95_ms": setup_p95,
        "send_median_ms": send_median,
        "send_p95_ms": send_p95,
        "receive_median_ms": receive_median,
        "receive_p95_ms": receive_p95,
        "send_throughput_median_ops_s": throughput_from_latency(
            message_count, send_median
        ),
        "send_throughput_p95_latency_ops_s": throughput_from_latency(
            message_count, send_p95
        ),
        "receive_throughput_median_ops_s": throughput_from_latency(
            message_count, receive_median
        ),
        "receive_throughput_p95_latency_ops_s": throughput_from_latency(
            message_count, receive_p95
        ),
        "approx_backlog_bytes": approx_backlog_bytes(message_count),
    }


def benchmark_producer_case(
    message_count: int,
    producer_count: int,
) -> dict[str, object]:
    concurrent_throughput_median, concurrent_throughput_p95 = measure_values(
        lambda: concurrent_send_throughput(message_count, producer_count)
    )
    return {
        "message_count": message_count,
        "producer_count": producer_count,
        "concurrent_send_median_ops_s": concurrent_throughput_median,
        "concurrent_send_p95_ops_s": concurrent_throughput_p95,
    }


def benchmark_broadcast_case(fanout: int) -> dict[str, object]:
    latency_median, latency_p95 = measure_values(lambda: broadcast_latency_ms(fanout))
    return {
        "fanout": fanout,
        "broadcast_median_ms": latency_median,
        "broadcast_p95_ms": latency_p95,
    }


def format_float(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def write_report(
    message_rows: list[dict[str, object]],
    producer_rows: list[dict[str, object]],
    broadcast_rows: list[dict[str, object]],
) -> None:
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        "# W5 Mailbox Benchmark",
        "",
        "## Scope",
        "",
        (
            "This benchmark measures the in-process synchronous AgentMailbox "
            "only. It covers setup, send, receive, concurrent producer send, "
            "broadcast fan-out, and approximate backlog size. It does not "
            "measure Worker execution, crash recovery, durable replay, "
            "exactly-once delivery, or Multi-Agent speedup."
        ),
        "",
        "## Environment",
        "",
        f"- Generated at: {generated_at}",
        f"- Base HEAD: `{base_head()}`",
        f"- Commit SHA: `{commit_sha()}`",
        f"- Working tree: `{working_tree_state()}`",
        f"- OS: `{platform.platform()}`",
        f"- mailbox.py SHA-256: `{file_sha256('codeteam/agent_team/mailbox.py')}`",
        (
            "- benchmark_mailbox.py SHA-256: "
            f"`{file_sha256('evals/week5/benchmark_mailbox.py')}`"
        ),
        f"- Python: `{platform.python_implementation()} {platform.python_version()}`",
        f"- Random seed: `{SEED}`",
        f"- Warmup runs per case: `{WARMUP_RUNS}`",
        f"- Measured runs per case: `{MEASURED_RUNS}`",
        "",
        "## Message Hot Path Results",
        "",
        (
            "| messages | setup median ms | setup p95 ms | "
            "send median ms | send p95 ms | receive median ms | "
            "receive p95 ms | send throughput median ops/s | "
            "send throughput at p95 latency ops/s | "
            "receive throughput median ops/s | "
            "receive throughput at p95 latency ops/s | "
            "approx backlog bytes |"
        ),
        (
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
            "---:|---:|"
        ),
    ]
    for row in message_rows:
        formatted = {key: format_float(value) for key, value in row.items()}
        lines.append(
            "| {message_count} | {setup_median_ms} | "
            "{setup_p95_ms} | {send_median_ms} | {send_p95_ms} | "
            "{receive_median_ms} | {receive_p95_ms} | "
            "{send_throughput_median_ops_s} | "
            "{send_throughput_p95_latency_ops_s} | "
            "{receive_throughput_median_ops_s} | "
            "{receive_throughput_p95_latency_ops_s} | "
            "{approx_backlog_bytes} |".format(**formatted)
        )

    lines.extend(
        [
            "",
            "## Concurrent Producer Results",
            "",
            (
                "| messages | producers | concurrent send median ops/s | "
                "concurrent send p95 ops/s |"
            ),
            "|---:|---:|---:|---:|",
        ]
    )
    for row in producer_rows:
        formatted = {key: format_float(value) for key, value in row.items()}
        lines.append(
            "| {message_count} | {producer_count} | "
            "{concurrent_send_median_ops_s} | "
            "{concurrent_send_p95_ops_s} |".format(**formatted)
        )

    lines.extend(
        [
            "",
            "## Broadcast Results",
            "",
            "| fanout | broadcast median ms | broadcast p95 ms |",
            "|---:|---:|---:|",
        ]
    )
    for row in broadcast_rows:
        formatted = {key: format_float(value) for key, value in row.items()}
        lines.append(
            "| {fanout} | {broadcast_median_ms} | {broadcast_p95_ms} |".format(
                **formatted
            )
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "- Setup latency is reported separately from send and receive "
                "hot paths."
            ),
            (
                "- Concurrent producer throughput measures in-process thread "
                "contention only; it is not a distributed queue benchmark."
            ),
            (
                "- Approximate backlog bytes are based on serialized message "
                "size, not process RSS."
            ),
            "- These results do not prove end-to-end Multi-Agent acceleration.",
            "",
            "## Deferred Metrics",
            "",
            (
                "- Crash recovery: DEFERRED / NOT_RUN until Day5 heartbeat and "
                "failure detection exist."
            ),
            (
                "- Durable replay latency: DEFERRED / NOT_RUN until Day6 durable "
                "Team Task Store exists."
            ),
            (
                "- Exactly-once delivery: DEFERRED / NOT_RUN; it requires ack/nack, "
                "dedupe, and durable transaction semantics."
            ),
        ]
    )
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    random.seed(SEED)
    message_rows: list[dict[str, object]] = []
    producer_rows: list[dict[str, object]] = []
    broadcast_rows: list[dict[str, object]] = []
    for message_count in MESSAGE_COUNTS:
        row = benchmark_message_case(message_count)
        message_rows.append(row)
        print(
            f"messages={message_count:5} "
            f"send_ms={row['send_median_ms']:.3f} "
            f"receive_ms={row['receive_median_ms']:.3f}"
        )
        for producer_count in PRODUCER_COUNTS:
            producer_row = benchmark_producer_case(message_count, producer_count)
            producer_rows.append(producer_row)
            print(
                f"messages={message_count:5} producers={producer_count:2} "
                f"concurrent_ops_s="
                f"{producer_row['concurrent_send_median_ops_s']:.1f}"
            )
    for fanout in BROADCAST_FANOUTS:
        row = benchmark_broadcast_case(fanout)
        broadcast_rows.append(row)
        print(
            f"fanout={fanout:2} "
            f"broadcast_ms={row['broadcast_median_ms']:.3f}"
        )
    write_report(message_rows, producer_rows, broadcast_rows)
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
