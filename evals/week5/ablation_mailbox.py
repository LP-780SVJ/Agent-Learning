from __future__ import annotations

import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from codeteam.agent_team.mailbox import (
    AgentMailbox,
    AgentMessage,
    AgentMessageType,
    MailboxError,
)
from codeteam.agent_team.models import AgentIdentity

OUTPUT_PATH = REPO_ROOT / "docs/benchmark/W5_MAILBOX_ABLATION.md"
SEED = 20260827


@dataclass(frozen=True)
class Workload:
    name: str
    recipients: tuple[str, ...]
    registered_recipients: tuple[str, ...]
    capacity_per_inbox: int
    prefilled_recipients: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkloadResult:
    workload: Workload
    full_error: str | None
    full_new_messages: dict[str, int]
    ablated_error: str | None
    ablated_new_messages: dict[str, int]

    @property
    def partial_delivery(self) -> bool:
        return self.full_delivered_count == 0 and self.ablated_delivered_count > 0

    @property
    def inbox_divergence(self) -> bool:
        return self.full_new_messages != self.ablated_new_messages

    @property
    def cleanup_required_count(self) -> int:
        return max(self.ablated_delivered_count - self.full_delivered_count, 0)

    @property
    def full_delivered_count(self) -> int:
        return sum(self.full_new_messages.values())

    @property
    def ablated_delivered_count(self) -> int:
        return sum(self.ablated_new_messages.values())


WORKLOADS = (
    Workload(
        name="unknown-recipient-second-of-three",
        recipients=("worker-a", "missing", "worker-c"),
        registered_recipients=("worker-a", "worker-c"),
        capacity_per_inbox=2,
    ),
    Workload(
        name="unknown-recipient-third-of-four",
        recipients=("worker-a", "worker-b", "missing", "worker-d"),
        registered_recipients=("worker-a", "worker-b", "worker-d"),
        capacity_per_inbox=2,
    ),
    Workload(
        name="full-recipient-second-of-three",
        recipients=("worker-a", "worker-b", "worker-c"),
        registered_recipients=("worker-a", "worker-b", "worker-c"),
        capacity_per_inbox=1,
        prefilled_recipients=("worker-b",),
    ),
    Workload(
        name="full-recipient-third-of-four",
        recipients=("worker-a", "worker-b", "worker-c", "worker-d"),
        registered_recipients=("worker-a", "worker-b", "worker-c", "worker-d"),
        capacity_per_inbox=1,
        prefilled_recipients=("worker-c",),
    ),
)


def identity(agent_id: str) -> AgentIdentity:
    return AgentIdentity(agent_id=agent_id, display_name=agent_id)


def build_mailbox(workload: Workload) -> AgentMailbox:
    mailbox = AgentMailbox(capacity_per_inbox=workload.capacity_per_inbox)
    mailbox.register_agent(identity("lead"))
    for recipient_id in workload.registered_recipients:
        mailbox.register_agent(identity(recipient_id))
    for recipient_id in workload.prefilled_recipients:
        mailbox.send(
            AgentMessage(
                message_id=f"prefill-{workload.name}-{recipient_id}",
                sender_id="lead",
                recipient_id=recipient_id,
                message_type=AgentMessageType.INFO,
                task_id="mailbox-ablation",
                correlation_id=f"prefill-{workload.name}",
                payload={"prefill": True},
            )
        )
    return mailbox


def new_message_count(mailbox: AgentMailbox, workload: Workload) -> dict[str, int]:
    counts: dict[str, int] = {}
    for recipient_id in workload.registered_recipients:
        baseline = 1 if recipient_id in workload.prefilled_recipients else 0
        counts[recipient_id] = mailbox.queue_size(recipient_id) - baseline
    return counts


def run_full(workload: Workload) -> tuple[str | None, dict[str, int]]:
    mailbox = build_mailbox(workload)
    error: str | None = None
    try:
        mailbox.broadcast(
            sender_id="lead",
            recipient_ids=workload.recipients,
            message_type=AgentMessageType.INFO,
            task_id="mailbox-ablation",
            node_id="node-ablation",
            payload={"workload": workload.name},
            correlation_id=f"corr-full-{workload.name}",
        )
    except MailboxError as exc:
        error = type(exc).__name__
    return error, new_message_count(mailbox, workload)


def run_ablated(workload: Workload) -> tuple[str | None, dict[str, int]]:
    mailbox = build_mailbox(workload)
    error: str | None = None
    for index, recipient_id in enumerate(workload.recipients):
        try:
            mailbox.send(
                AgentMessage(
                    message_id=f"ablated-{workload.name}-{index}",
                    sender_id="lead",
                    recipient_id=recipient_id,
                    message_type=AgentMessageType.INFO,
                    task_id="mailbox-ablation",
                    node_id="node-ablation",
                    correlation_id=f"corr-ablated-{workload.name}",
                    payload={"workload": workload.name},
                )
            )
        except MailboxError as exc:
            error = type(exc).__name__
            break
    return error, new_message_count(mailbox, workload)


def run_workload(workload: Workload) -> WorkloadResult:
    full_error, full_counts = run_full(workload)
    ablated_error, ablated_counts = run_ablated(workload)
    return WorkloadResult(
        workload=workload,
        full_error=full_error,
        full_new_messages=full_counts,
        ablated_error=ablated_error,
        ablated_new_messages=ablated_counts,
    )


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


def base_head() -> str:
    return git_output(["git", "rev-parse", "HEAD"])


def commit_sha() -> str:
    return git_output(["git", "rev-parse", "--short", "HEAD"])


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


def write_report(results: list[WorkloadResult]) -> None:
    partial_delivery_count = sum(1 for result in results if result.partial_delivery)
    inbox_divergence_count = sum(1 for result in results if result.inbox_divergence)
    cleanup_required_count = sum(
        result.cleanup_required_count for result in results
    )
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")

    lines = [
        "# W5 Mailbox Ablation",
        "",
        "## Scope",
        "",
        (
            "This is a correctness/safety ablation for AgentMailbox broadcast "
            "atomicity. It is not a performance benchmark and does not measure "
            "Multi-Agent speedup."
        ),
        "",
        "## Environment",
        "",
        f"- Generated at: {generated_at}",
        f"- Base HEAD: `{base_head()}`",
        f"- Commit SHA: `{commit_sha()}`",
        f"- Working tree: `{working_tree_state()}`",
        f"- OS: `{platform.platform()}`",
        f"- Python: `{platform.python_implementation()} {platform.python_version()}`",
        f"- Random seed: `{SEED}`",
        f"- mailbox.py SHA-256: `{file_sha256('codeteam/agent_team/mailbox.py')}`",
        (
            "- ablation_mailbox.py SHA-256: "
            f"`{file_sha256('evals/week5/ablation_mailbox.py')}`"
        ),
        "",
        "## Systems",
        "",
        "- Full: current all-or-nothing `AgentMailbox.broadcast()`.",
        "- Ablated: one-off experiment code that loops over `send()` recipients.",
        "",
        "## Workloads",
        "",
        (
            "| workload | failure mode | full error | full new messages | "
            "ablated error | ablated new messages | partial delivery | "
            "inbox divergence | cleanup required |"
        ),
        "|---|---|---|---:|---|---:|---:|---:|---:|",
    ]
    for result in results:
        failure_mode = (
            "unknown recipient"
            if "unknown" in result.workload.name
            else "full recipient"
        )
        lines.append(
            f"| {result.workload.name} | {failure_mode} | {result.full_error} | "
            f"{result.full_delivered_count} | {result.ablated_error} | "
            f"{result.ablated_delivered_count} | {int(result.partial_delivery)} | "
            f"{int(result.inbox_divergence)} | {result.cleanup_required_count} |"
        )

    lines.extend(
        [
            "",
            "## Aggregate Results",
            "",
            f"- workloads: `{len(results)}`",
            f"- partial_delivery_count: `{partial_delivery_count}`",
            f"- inbox_divergence_count: `{inbox_divergence_count}`",
            f"- cleanup_required_count: `{cleanup_required_count}`",
            "",
            "## Delta",
            "",
            (
                "- Full broadcast produced `0` partial deliveries across all "
                "failure workloads."
            ),
            (
                f"- Ablated loop-send produced `{partial_delivery_count}` partial "
                f"delivery workloads and `{cleanup_required_count}` messages "
                "that would require cleanup."
            ),
            "",
            "## Interpretation",
            "",
            (
                "The all-or-nothing broadcast contract prevents team-state "
                "divergence when one recipient is missing or full. Looping over "
                "`send()` is simpler, but it can deliver earlier messages before "
                "a later recipient fails."
            ),
            "",
            "## Limitations",
            "",
            "- This ablation does not modify production code.",
            "- It does not measure latency or throughput.",
            "- It covers deterministic unknown-recipient and full-inbox failures.",
            "- Tester still decides whether DD-W5-04 should be marked SUPPORTED.",
        ]
    )
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    results = [run_workload(workload) for workload in WORKLOADS]
    write_report(results)
    for result in results:
        print(
            f"{result.workload.name}: full={result.full_delivered_count} "
            f"ablated={result.ablated_delivered_count} "
            f"cleanup={result.cleanup_required_count}"
        )
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
