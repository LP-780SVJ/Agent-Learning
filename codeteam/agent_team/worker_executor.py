"""Adapter from durable Team claims to the existing single-Agent runtime."""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeStatus,
)
from codeteam.agent_team.models import WorkerAssignment
from codeteam.agent_team.scheduler import TaskClaim
from codeteam.agent_team.team_models import (
    NodeBudgetAllocation,
    NodeExecutionResult,
    NodeTiming,
)
from codeteam.redaction import (
    redact_sensitive_data,
    redact_sensitive_text,
    safe_exception_details,
)


class CodingRuntime(Protocol):
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult: ...


class MonotonicClock(Protocol):
    def monotonic(self) -> float: ...


class SystemMonotonicClock:
    def monotonic(self) -> float:
        return time.monotonic()


class RetryableWorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerExecutionRequest:
    parent_request: CodingAgentRunRequest
    assignment: WorkerAssignment
    claim: TaskClaim
    workspace_root: Path
    budget: NodeBudgetAllocation
    ready_at: float


class WorkerExecutor:
    _RETRYABLE_FAILURES = frozenset(
        {
            "provider_transient",
            "rate_limit",
            "timeout",
            "worker_transient",
        }
    )

    def __init__(
        self,
        runtime: CodingRuntime,
        *,
        clock: MonotonicClock | None = None,
    ) -> None:
        self._runtime = runtime
        self._clock = clock or SystemMonotonicClock()

    def execute(self, request: WorkerExecutionRequest) -> NodeExecutionResult:
        started = self._clock.monotonic()
        child_request = self.build_runtime_request(request)
        try:
            result = self._runtime.run(child_request)
        except RetryableWorkerError as error:
            return self._failure_result(
                request,
                started=started,
                error=error,
                retryable=True,
            )
        except Exception as error:  # noqa: BLE001 - structured Worker boundary.
            return self._failure_result(
                request,
                started=started,
                error=error,
                retryable=False,
            )

        safe_result = CodingAgentRunResult.model_validate(
            redact_sensitive_data(result.model_dump(mode="python"))
        )
        retryable = (
            safe_result.status is RuntimeStatus.FAILED
            and safe_result.failure_category in self._RETRYABLE_FAILURES
        )
        return NodeExecutionResult(
            node_id=request.claim.node_id,
            worker_id=request.claim.worker_id,
            runtime_id=request.claim.runtime_id,
            worker_generation=request.claim.worker_generation,
            attempt=request.claim.attempt,
            status=safe_result.status,
            runtime_result=safe_result,
            retryable=retryable,
            failure_category=safe_result.failure_category,
            error_code=safe_result.failure_category,
            error=redact_sensitive_text(safe_result.error) if safe_result.error else None,
            timing=NodeTiming(
                ready_at=request.ready_at,
                started_at=started,
                finished_at=self._clock.monotonic(),
            ),
        )

    def build_runtime_request(
        self, request: WorkerExecutionRequest
    ) -> CodingAgentRunRequest:
        budget = request.budget
        if budget.max_steps < 1 or budget.max_tool_calls < 1:
            raise ValueError("node has no dispatchable budget")
        parent = request.parent_request
        reserve = parent.finalization_reserve_steps
        if reserve is None:
            reserve = max(1, math.ceil(budget.max_steps * 0.20))
        reserve = min(reserve, budget.max_steps)
        payload = parent.model_dump()
        payload.update(
            {
                "task_id": _child_runtime_task_id(
                    parent.task_id,
                    request.claim.node_id,
                    request.claim.attempt,
                ),
                "task": _render_assignment(request.assignment),
                "workspace_root": request.workspace_root,
                "workspace_write_allowed": request.assignment.allow_workspace_write,
                "max_steps": budget.max_steps,
                "effective_max_steps": budget.max_steps,
                "step_offset": 0,
                "finalization_reserve_steps": reserve,
                "max_tool_calls": budget.max_tool_calls,
                "max_repairs": budget.max_repairs,
                "max_protocol_repairs": budget.max_protocol_repairs,
                "initial_messages": (),
                "initial_protocol_repair_streak": 0,
            }
        )
        # model_copy(update=...) intentionally skips Pydantic validation. A child
        # budget is a new trust boundary, so rebuild the request formally.
        return CodingAgentRunRequest.model_validate(payload)

    def _failure_result(
        self,
        request: WorkerExecutionRequest,
        *,
        started: float,
        error: Exception,
        retryable: bool,
    ) -> NodeExecutionResult:
        category = "worker_transient" if retryable else "worker_runtime_failure"
        details = safe_exception_details(error, code=category)
        return NodeExecutionResult(
            node_id=request.claim.node_id,
            worker_id=request.claim.worker_id,
            runtime_id=request.claim.runtime_id,
            worker_generation=request.claim.worker_generation,
            attempt=request.claim.attempt,
            status=RuntimeStatus.FAILED,
            retryable=retryable,
            failure_category=category,
            error_code=details.code,
            exception_type=details.exception_type,
            error_summary_sha256=details.summary_sha256,
            error=details.message,
            timing=NodeTiming(
                ready_at=request.ready_at,
                started_at=started,
                finished_at=self._clock.monotonic(),
            ),
        )


def _render_assignment(assignment: WorkerAssignment) -> str:
    relevant = ", ".join(assignment.relevant_files) or "discover from initial context"
    verification = assignment.verification or "Use the task's configured checks."
    write_scope = (
        "Workspace patching is allowed for this assignment."
        if assignment.allow_workspace_write
        else "This is read-only work. Do not modify the workspace."
    )
    return "\n".join(
        (
            f"Complete only Team node {assignment.assignment_id}.",
            f"Goal: {assignment.goal}",
            f"Expected output: {assignment.expected_output}",
            f"Relevant files: {relevant}",
            f"Verification: {verification}",
            write_scope,
            "Do not take ownership of other DAG nodes.",
        )
    )


def _child_runtime_task_id(parent_task_id: str, node_id: str, attempt: int) -> str:
    """Build a stable ID accepted by Worktree and Checkpoint boundaries."""

    identity = f"{parent_task_id}\0{node_id}\0{attempt}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    readable = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        f"{parent_task_id}-{node_id}-attempt-{attempt}",
    ).strip("-_")
    prefix = (readable or "team-node")[:80].rstrip("-_") or "team-node"
    return f"{prefix}-{digest}"
