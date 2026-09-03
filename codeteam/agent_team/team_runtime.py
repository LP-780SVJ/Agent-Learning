"""Bounded Team Coding Runtime built on the durable Day5/Day6 control plane."""

from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    RuntimeArtifactRef,
    RuntimeStatus,
)
from codeteam.agent_team.dag import TaskStatus
from codeteam.agent_team.mailbox import AgentMessage, AgentMessageType
from codeteam.agent_team.models import AgentStatus, WorkerAssignment
from codeteam.agent_team.persistence_models import TeamStateSnapshot
from codeteam.agent_team.scheduler import TaskClaim
from codeteam.agent_team.team_artifacts import TeamRunArtifactStore
from codeteam.agent_team.team_budget import (
    TeamBudgetError,
    TeamBudgetLedger,
    WeightedTeamBudgetPolicy,
)
from codeteam.agent_team.team_models import (
    NodeExecutionResult,
    TeamBudgetAllocation,
    TeamBudgetUsage,
    TeamCodingRunResult,
    TeamControlStatus,
    TeamFailureCategory,
    TeamMetrics,
    TeamProgressState,
    TeamRunArtifact,
    TeamUsage,
)
from codeteam.agent_team.team_planning import TeamPlan, TeamPlanner
from codeteam.agent_team.team_runtime_provider import (
    TeamRuntimeHandle,
    TeamRuntimeProvider,
    TeamRuntimeProviderError,
)
from codeteam.agent_team.worker_executor import (
    WorkerExecutionRequest,
    WorkerExecutor,
)
from codeteam.agent_team.workspace_evidence import (
    GitMetadataBaseline,
    TrustedWorkspaceEvidence,
    capture_git_metadata_baseline,
    collect_trusted_workspace_evidence,
)
from codeteam.redaction import (
    redact_sensitive_data,
    redact_sensitive_text,
    safe_exception_details,
)


class TeamRuntimeError(RuntimeError):
    pass


class UnsafeSharedWorkspaceError(TeamRuntimeError):
    pass


class TeamResultProtocolError(TeamRuntimeError):
    pass


class RuntimeClock(Protocol):
    def monotonic(self) -> float: ...


class SystemRuntimeClock:
    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class _ActiveExecution:
    claim: TaskClaim
    assignment: WorkerAssignment


class TeamCodingRuntime:
    """One controller thread owns state; Worker threads only return values."""

    def __init__(
        self,
        *,
        planner: TeamPlanner,
        worker_executor: WorkerExecutor,
        runtime_provider: TeamRuntimeProvider,
        budget_policy: WeightedTeamBudgetPolicy | None = None,
        max_workers: int = 1,
        clock: RuntimeClock | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._planner = planner
        self._worker_executor = worker_executor
        self._runtime_provider = runtime_provider
        self._budget_policy = budget_policy or WeightedTeamBudgetPolicy()
        self._max_workers = max_workers
        self._clock = clock or SystemRuntimeClock()

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        return self.run_team(request).runtime_result

    def run_team(self, request: CodingAgentRunRequest) -> TeamCodingRunResult:
        request = CodingAgentRunRequest.model_validate(request.model_dump())
        started = self._clock.monotonic()
        try:
            plan = self._planner.plan(request)
            assignments = plan.lead_result.assignments
            if self._max_workers > 1 and any(
                assignment.allow_workspace_write for assignment in assignments
            ):
                raise UnsafeSharedWorkspaceError(
                    "Week5 does not run concurrent writable nodes in one worktree"
                )
            allocation = self._budget_policy.allocate(
                parent=request,
                assignments=assignments,
            )
        except (ValueError, TeamBudgetError, UnsafeSharedWorkspaceError) as error:
            return _pre_runtime_failure(request, started, error, self._clock)

        try:
            handle = self._runtime_provider.create(request=request, plan=plan)
        except (OSError, TeamRuntimeProviderError) as error:
            return _pre_runtime_failure(request, started, error, self._clock)
        artifact_store = TeamRunArtifactStore(handle.session_dir)
        git_metadata_baseline = capture_git_metadata_baseline(request.workspace_root)
        artifact_store.write_progress(
            TeamProgressState(
                task_id=request.task_id,
                allocation=allocation,
            )
        )
        ledger = TeamBudgetLedger(
            allocation,
            limits=self._budget_policy.limits,
        )
        return self._execute_team(
            request=request,
            plan=plan,
            handle=handle,
            allocation=allocation,
            ledger=ledger,
            node_results=[],
            artifact_store=artifact_store,
            started=started,
            resumed=False,
            git_metadata_baseline=git_metadata_baseline,
        )

    def resume_team(
        self,
        request: CodingAgentRunRequest,
        *,
        plan: TeamPlan,
        handle: TeamRuntimeHandle,
    ) -> TeamCodingRunResult:
        """Continue only from an already reconciled and hydrated Day6 runtime."""
        request = CodingAgentRunRequest.model_validate(request.model_dump())
        plan = TeamPlan.model_validate(plan.model_dump())
        started = self._clock.monotonic()
        expected_nodes = {
            assignment.assignment_id for assignment in plan.lead_result.assignments
        }
        snapshot = handle.runtime.snapshot
        if request.task_id != plan.lead_result.task_id or set(snapshot.tasks) != expected_nodes:
            raise TeamResultProtocolError("resume request, plan and durable DAG disagree")
        if snapshot.dependencies != _dependencies_for_plan(plan):
            raise TeamResultProtocolError("resume plan dependencies changed")
        if self._max_workers > 1 and any(
            assignment.allow_workspace_write
            for assignment in plan.lead_result.assignments
        ):
            raise UnsafeSharedWorkspaceError(
                "Week5 does not resume concurrent writable nodes in one worktree"
            )

        expected_allocation = self._budget_policy.allocate(
            parent=request,
            assignments=plan.lead_result.assignments,
        )
        artifact_store = TeamRunArtifactStore(handle.session_dir)
        git_metadata_baseline = capture_git_metadata_baseline(request.workspace_root)
        progress = artifact_store.load_progress()
        if progress.task_id != request.task_id or progress.allocation != expected_allocation:
            raise TeamResultProtocolError("durable Team budget contract changed")
        progress = _recover_progress_references(snapshot, progress)
        ledger = TeamBudgetLedger(
            progress.allocation,
            limits=self._budget_policy.limits,
        )
        node_results = [
            artifact_store.load_node_result(reference)
            for reference in progress.node_artifacts
        ]
        proven_attempts: set[tuple[str, int]] = set()
        for result in node_results:
            proven_attempts.add((result.node_id, result.attempt))
            if result.runtime_result is not None:
                ledger.record(result.node_id, result.runtime_result)
        for node_id, record in snapshot.tasks.items():
            if record.attempt > 0 and (node_id, record.attempt) not in proven_attempts:
                if record.status is TaskStatus.COMPLETED:
                    raise TeamResultProtocolError(
                        f"completed node lacks durable result evidence: {node_id}"
                    )
                ledger.exhaust_unproven_attempt(node_id)
        artifact_store.write_progress(progress)
        return self._execute_team(
            request=request,
            plan=plan,
            handle=handle,
            allocation=progress.allocation,
            ledger=ledger,
            node_results=node_results,
            artifact_store=artifact_store,
            started=started,
            resumed=True,
            git_metadata_baseline=git_metadata_baseline,
        )

    def _execute_team(
        self,
        *,
        request: CodingAgentRunRequest,
        plan: TeamPlan,
        handle: TeamRuntimeHandle,
        allocation: TeamBudgetAllocation,
        ledger: TeamBudgetLedger,
        node_results: list[NodeExecutionResult],
        artifact_store: TeamRunArtifactStore,
        started: float,
        resumed: bool,
        git_metadata_baseline: GitMetadataBaseline,
    ) -> TeamCodingRunResult:
        assignments = plan.lead_result.assignments
        assignment_by_id = {
            assignment.assignment_id: assignment for assignment in assignments
        }
        ready_at: dict[str, float] = {}
        messages_sent = 0
        messages_acked = 0
        max_parallelism = 0
        failure_category: TeamFailureCategory | None = None
        failure_reason: str | None = None
        control_status = TeamControlStatus.FAILED
        active: dict[Future[NodeExecutionResult], _ActiveExecution] = {}
        executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="codeteam-worker",
        )

        handle.runtime.persist(
            event_type="team.run.resumed" if resumed else "team.run.started",
            payload={
                "task_id": request.task_id,
                "node_count": len(assignments),
                "max_workers": self._max_workers,
            },
        )
        try:
            handle.runtime.schedule()
            while True:
                _capture_ready_times(handle, ready_at, self._clock.monotonic())
                while len(active) < self._max_workers:
                    dispatched = self._dispatch_one(
                        request=request,
                        handle=handle,
                        ledger=ledger,
                        assignment_by_id=assignment_by_id,
                        ready_at=ready_at,
                        executor=executor,
                        active=active,
                    )
                    if not dispatched:
                        break
                    max_parallelism = max(max_parallelism, len(active))

                records = handle.runtime.scheduler.runtime_records
                if not active:
                    if all(
                        record.status is TaskStatus.COMPLETED
                        for record in records.values()
                    ):
                        control_status = TeamControlStatus.COMPLETED
                        break
                    if any(
                        record.status in {TaskStatus.FAILED, TaskStatus.BLOCKED}
                        for record in records.values()
                    ) and all(_terminal(record.status) for record in records.values()):
                        control_status = TeamControlStatus.FAILED
                        failure_category, failure_reason = (
                            _classify_terminal_node_failures(node_results)
                        )
                        break
                    if handle.runtime.snapshot.waiting_for_worker:
                        control_status = TeamControlStatus.PAUSED
                        failure_category = TeamFailureCategory.NO_COMPATIBLE_WORKER
                        failure_reason = "no compatible Worker is available"
                        break
                    if _ready_task_lacks_available_worker(
                        handle,
                        assignment_by_id,
                    ):
                        control_status = TeamControlStatus.PAUSED
                        failure_category = TeamFailureCategory.NO_COMPATIBLE_WORKER
                        failure_reason = "no compatible Worker is currently available"
                        break
                    control_status = TeamControlStatus.FAILED
                    failure_category = TeamFailureCategory.SCHEDULER
                    failure_reason = "Team made no progress with non-terminal tasks"
                    break

                completed, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
                for future in sorted(
                    completed,
                    key=lambda item: active[item].claim.node_id,
                ):
                    execution = active.pop(future)
                    result = future.result()
                    node_results.append(result)
                    outcome = self._publish_worker_result(
                        request=request,
                        handle=handle,
                        execution=execution,
                        result=result,
                        artifact_store=artifact_store,
                        ledger=ledger,
                    )
                    messages_sent += 1
                    messages_acked += 1
                    if outcome is RuntimeStatus.PAUSED:
                        control_status = TeamControlStatus.PAUSED
                        failure_category = TeamFailureCategory.INTERRUPTED
                        failure_reason = result.error or "Worker paused"
                        for pending in active:
                            pending.cancel()
                        active.clear()
                        break
                if control_status is TeamControlStatus.PAUSED:
                    break
        except BaseException as interrupt:
            for future in active:
                future.cancel()
            try:
                handle.runtime.persist(
                    event_type="team.run.interrupted",
                    payload={"task_id": request.task_id},
                )
            except Exception as persistence_error:  # noqa: BLE001
                interrupt.add_note(
                    "Team interruption audit also failed: "
                    f"{type(persistence_error).__name__}: {persistence_error}"
                )
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

        finished = self._clock.monotonic()
        if failure_category is None and control_status is TeamControlStatus.FAILED:
            failure_category = TeamFailureCategory.WORKER_RUNTIME
        handle.runtime.persist(
            event_type=f"team.run.{control_status.value}",
            payload={
                "task_id": request.task_id,
                "failure_category": failure_category.value
                if failure_category is not None
                else None,
                "failure_reason": failure_reason,
            },
        )
        return _finalize_result(
            request=request,
            handle=handle,
            assignment_by_id=assignment_by_id,
            node_results=node_results,
            allocation=allocation,
            budget_usage=ledger.usage,
            control_status=control_status,
            failure_category=failure_category,
            failure_reason=failure_reason,
            wall_seconds=max(0.0, finished - started),
            max_parallelism=max_parallelism,
            configured_workers=self._max_workers,
            messages_sent=messages_sent,
            messages_acked=messages_acked,
            artifact_store=artifact_store,
            git_metadata_baseline=git_metadata_baseline,
        )

    def _dispatch_one(
        self,
        *,
        request: CodingAgentRunRequest,
        handle: TeamRuntimeHandle,
        ledger: TeamBudgetLedger,
        assignment_by_id: dict[str, WorkerAssignment],
        ready_at: dict[str, float],
        executor: ThreadPoolExecutor,
        active: dict[Future[NodeExecutionResult], _ActiveExecution],
    ) -> bool:
        for node_id in handle.runtime.scheduler.queue:
            assignment = assignment_by_id[node_id]
            for worker in handle.runtime.registry.compatible_assignment(assignment):
                worker_id = worker.info.identity.agent_id
                worker_record = handle.runtime.registry.runtime(worker_id)
                if worker_record.status is not AgentStatus.READY:
                    continue
                lease = handle.runtime.registry.lease(worker_id)
                claim = handle.runtime.claim(lease)
                if claim is None:
                    continue
                handle.runtime.start(claim)
                remaining = ledger.remaining(claim.node_id)
                if not ledger.can_dispatch(claim.node_id):
                    handle.runtime.fail(
                        claim,
                        "node budget exhausted before dispatch",
                        retryable=False,
                    )
                    return True
                future = executor.submit(
                    self._worker_executor.execute,
                    WorkerExecutionRequest(
                        parent_request=request,
                        assignment=assignment,
                        claim=claim,
                        workspace_root=request.workspace_root,
                        budget=remaining,
                        ready_at=ready_at.get(claim.node_id, self._clock.monotonic()),
                    ),
                )
                active[future] = _ActiveExecution(
                    claim=claim,
                    assignment=assignment,
                )
                return True
        return False

    def _publish_worker_result(
        self,
        *,
        request: CodingAgentRunRequest,
        handle: TeamRuntimeHandle,
        execution: _ActiveExecution,
        result: NodeExecutionResult,
        artifact_store: TeamRunArtifactStore,
        ledger: TeamBudgetLedger,
    ) -> RuntimeStatus:
        reference = artifact_store.write_node_result(result)
        message = AgentMessage(
            message_id=f"msg-{uuid4().hex}",
            sender_id=execution.claim.worker_id,
            recipient_id=handle.lead_id,
            message_type=(
                AgentMessageType.TASK_COMPLETED
                if result.status is RuntimeStatus.COMPLETED
                else AgentMessageType.TASK_FAILED
            ),
            task_id=request.task_id,
            node_id=execution.claim.node_id,
            correlation_id=f"claim-{execution.claim.node_id}-{execution.claim.attempt}",
            payload={
                "runtime_id": result.runtime_id,
                "worker_generation": result.worker_generation,
                "attempt": result.attempt,
                "artifact": reference.model_dump(mode="json"),
            },
        )
        handle.runtime.send_message(message)
        message_claim = handle.runtime.claim_message(handle.lead_id)
        if message_claim is None:
            raise TeamResultProtocolError("published Worker result cannot be claimed")
        loaded = artifact_store.load_node_result(reference)
        _validate_result_fence(execution.claim, message_claim.message, loaded)

        if loaded.runtime_result is not None:
            try:
                ledger.record(loaded.node_id, loaded.runtime_result)
            except TeamBudgetError as error:
                handle.runtime.fail(
                    execution.claim,
                    str(error),
                    retryable=False,
                )
                handle.runtime.ack_message(message_claim)
                return RuntimeStatus.FAILED
        progress = artifact_store.load_progress()
        artifact_store.write_progress(
            progress.model_copy(
                update={"node_artifacts": (*progress.node_artifacts, reference)}
            )
        )

        if loaded.status is RuntimeStatus.COMPLETED:
            handle.runtime.complete(execution.claim)
        elif loaded.status is RuntimeStatus.FAILED:
            handle.runtime.fail(
                execution.claim,
                loaded.error or "Worker failed without an error message",
                retryable=loaded.retryable and ledger.can_dispatch(loaded.node_id),
            )
        elif loaded.status is RuntimeStatus.PAUSED:
            # Keep RUNNING durable state. A future process must reconcile it; it
            # must never be mistaken for a completed or retryable attempt.
            pass
        else:  # pragma: no cover - RuntimeStatus is exhaustive.
            raise TeamResultProtocolError(f"unknown Worker status: {loaded.status}")
        handle.runtime.ack_message(message_claim)
        return loaded.status


def _validate_result_fence(
    claim: TaskClaim,
    message: AgentMessage,
    result: NodeExecutionResult,
) -> None:
    payload = message.payload
    expected = (
        claim.node_id,
        claim.worker_id,
        claim.runtime_id,
        claim.worker_generation,
        claim.attempt,
    )
    actual = (
        result.node_id,
        result.worker_id,
        result.runtime_id,
        result.worker_generation,
        result.attempt,
    )
    message_fence = (
        message.node_id,
        message.sender_id,
        payload.get("runtime_id"),
        payload.get("worker_generation"),
        payload.get("attempt"),
    )
    if actual != expected or message_fence != expected:
        raise TeamResultProtocolError("stale or mismatched Worker result fence")


def _dependencies_for_plan(plan: TeamPlan) -> dict[str, frozenset[str]]:
    dependencies: dict[str, set[str]] = {
        assignment.assignment_id: set()
        for assignment in plan.lead_result.assignments
    }
    for prerequisite, dependent in plan.dependencies:
        dependencies[dependent].add(prerequisite)
    return {
        node_id: frozenset(prerequisites)
        for node_id, prerequisites in sorted(dependencies.items())
    }


def _recover_progress_references(
    snapshot: TeamStateSnapshot,
    progress: TeamProgressState,
) -> TeamProgressState:
    references = list(progress.node_artifacts)
    known = {(reference.kind, reference.path, reference.sha256) for reference in references}
    for durable in snapshot.messages:
        payload = durable.message.payload
        candidate = payload.get("artifact")
        if not isinstance(candidate, dict):
            continue
        reference = RuntimeArtifactRef.model_validate(candidate)
        key = (reference.kind, reference.path, reference.sha256)
        if reference.kind == "team_node_result" and key not in known:
            references.append(reference)
            known.add(key)
    return TeamProgressState(
        task_id=progress.task_id,
        allocation=progress.allocation,
        node_artifacts=tuple(references),
    )


def _capture_ready_times(
    handle: TeamRuntimeHandle,
    ready_at: dict[str, float],
    now: float,
) -> None:
    for node_id, record in handle.runtime.scheduler.runtime_records.items():
        if record.status is TaskStatus.READY:
            ready_at.setdefault(node_id, now)


def _ready_task_lacks_available_worker(
    handle: TeamRuntimeHandle,
    assignments: dict[str, WorkerAssignment],
) -> bool:
    for node_id in handle.runtime.scheduler.queue:
        compatible = handle.runtime.registry.compatible_assignment(
            assignments[node_id]
        )
        if compatible and not any(
            handle.runtime.registry.runtime(worker.info.identity.agent_id).status
            is AgentStatus.READY
            for worker in compatible
        ):
            return True
    return False


def _terminal(status: TaskStatus) -> bool:
    return status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED}


def _classify_terminal_node_failures(
    node_results: list[NodeExecutionResult],
) -> tuple[TeamFailureCategory, str]:
    failures = [
        (item.node_id, item.failure_category)
        for item in node_results
        if item.status is not RuntimeStatus.COMPLETED and item.failure_category
    ]
    categories = {category for _, category in failures}
    if categories & {"max_steps", "max_tool_calls", "budget_exhausted"}:
        category = TeamFailureCategory.BUDGET
    elif categories & {"provider_blocked", "provider_failure", "provider_transient"}:
        category = TeamFailureCategory.PROVIDER
    elif categories & {
        "environment_failure",
        "sandbox_unavailable",
        "verification_environment_failed",
    }:
        category = TeamFailureCategory.ENVIRONMENT
    elif any("protocol" in item for item in categories):
        category = TeamFailureCategory.PROTOCOL
    else:
        category = TeamFailureCategory.WORKER_RUNTIME
    detail = ", ".join(
        f"{node_id}={failure_category}" for node_id, failure_category in failures
    )
    reason = "one or more Team nodes failed or were blocked"
    return category, f"{reason}: {detail}" if detail else reason


def _pre_runtime_failure(
    request: CodingAgentRunRequest,
    started: float,
    error: Exception,
    clock: RuntimeClock,
) -> TeamCodingRunResult:
    elapsed = max(0.0, clock.monotonic() - started)
    allocation = TeamBudgetAllocation(
        global_max_steps=request.max_steps,
        global_max_tool_calls=request.max_tool_calls,
        global_max_repairs=request.max_repairs,
        reserve_steps=0,
        reserve_tool_calls=0,
        nodes={},
    )
    if isinstance(error, TeamBudgetError):
        category = TeamFailureCategory.BUDGET
    elif isinstance(error, (OSError, TeamRuntimeProviderError)):
        category = TeamFailureCategory.ENVIRONMENT
    else:
        category = TeamFailureCategory.PLANNING
    details = safe_exception_details(error, code=category.value)
    runtime_result = CodingAgentRunResult(
        task_id=request.task_id,
        status=RuntimeStatus.FAILED,
        summary="Team failed before Worker execution began.",
        workspace_root=request.workspace_root,
        failure_category=category.value,
        failure_origin="team_runtime",
        error=details.message,
        duration_ms=int(elapsed * 1000),
        effective_max_steps=request.effective_max_steps or request.max_steps,
        finalization_reserve_steps=request.finalization_reserve_steps or 1,
    )
    artifact = TeamRunArtifact(
        task_id=request.task_id,
        control_status=TeamControlStatus.FAILED,
        dag_dependencies={},
        worker_assignments=(),
        node_results=(),
        trusted_workspace_evidence=TrustedWorkspaceEvidence(
            available=False,
            failure_code="workspace_evidence_not_collected",
            failure_reason="Team failed before workspace evidence collection.",
        ),
        budget=allocation,
        budget_usage=TeamBudgetUsage(),
        metrics=TeamMetrics(wall_seconds=elapsed),
        failure_category=category,
        failure_reason=details.message,
    )
    return TeamCodingRunResult(runtime_result=runtime_result, artifact=artifact)


def _finalize_result(
    *,
    request: CodingAgentRunRequest,
    handle: TeamRuntimeHandle,
    assignment_by_id: dict[str, WorkerAssignment],
    node_results: list[NodeExecutionResult],
    allocation: TeamBudgetAllocation,
    budget_usage: TeamBudgetUsage,
    control_status: TeamControlStatus,
    failure_category: TeamFailureCategory | None,
    failure_reason: str | None,
    wall_seconds: float,
    max_parallelism: int,
    configured_workers: int,
    messages_sent: int,
    messages_acked: int,
    artifact_store: TeamRunArtifactStore,
    git_metadata_baseline: GitMetadataBaseline,
) -> TeamCodingRunResult:
    successful = [
        item.runtime_result
        for item in node_results
        if item.runtime_result is not None
        and item.status is RuntimeStatus.COMPLETED
    ]
    all_runtime_results = [
        item.runtime_result
        for item in node_results
        if item.runtime_result is not None
    ]
    last_result = (successful or all_runtime_results)[-1] if all_runtime_results else None
    aggregate_worker_seconds = sum(item.timing.busy_seconds for item in node_results)
    scheduler_wait_seconds = sum(
        item.timing.scheduler_wait_seconds for item in node_results
    )
    metrics = TeamMetrics(
        wall_seconds=wall_seconds,
        aggregate_worker_seconds=aggregate_worker_seconds,
        scheduler_wait_seconds=scheduler_wait_seconds,
        max_parallelism=max_parallelism,
        configured_workers=configured_workers,
        retries=sum(item.attempt > 1 for item in node_results),
        messages_sent=messages_sent,
        messages_acked=messages_acked,
        usage=TeamUsage(
            input_tokens=budget_usage.input_tokens,
            output_tokens=budget_usage.output_tokens,
            cost_usd=budget_usage.cost_usd,
            tool_calls=budget_usage.tool_calls,
            steps=budget_usage.steps,
            repairs=budget_usage.repairs,
        ),
    )
    snapshot = handle.runtime.snapshot
    events = handle.store.load_events(handle.session_id)
    trusted_evidence = collect_trusted_workspace_evidence(
        request.workspace_root,
        git_metadata_baseline=git_metadata_baseline,
    )
    safe_failure_reason = (
        redact_sensitive_text(failure_reason) if failure_reason else None
    )
    artifact = TeamRunArtifact(
        task_id=request.task_id,
        control_status=control_status,
        dag_dependencies=snapshot.dependencies,
        worker_assignments=tuple(
            assignment_by_id[node_id] for node_id in sorted(assignment_by_id)
        ),
        node_results=tuple(node_results),
        trusted_workspace_evidence=trusted_evidence,
        blocked_nodes=tuple(
            node_id
            for node_id, record in sorted(snapshot.tasks.items())
            if record.status is TaskStatus.BLOCKED
        ),
        mailbox_messages=tuple(
            item.message.model_dump(mode="json") for item in snapshot.messages
        ),
        event_timeline=tuple(event.model_dump(mode="json") for event in events),
        budget=allocation,
        budget_usage=budget_usage,
        metrics=metrics,
        failure_category=failure_category,
        failure_reason=safe_failure_reason,
    )
    artifact = TeamRunArtifact.model_validate(
        redact_sensitive_data(artifact.model_dump(mode="python"))
    )
    team_reference = artifact_store.write_team_run(artifact)
    common = _aggregate_common_result(
        request=request,
        last_result=last_result,
        all_results=all_runtime_results,
        status=control_status,
        failure_category=failure_category,
        failure_reason=failure_reason,
        usage=budget_usage,
        wall_seconds=wall_seconds,
        team_reference=team_reference,
        trusted_evidence=trusted_evidence,
    )
    return TeamCodingRunResult(runtime_result=common, artifact=artifact)


def _aggregate_common_result(
    *,
    request: CodingAgentRunRequest,
    last_result: CodingAgentRunResult | None,
    all_results: list[CodingAgentRunResult],
    status: TeamControlStatus,
    failure_category: TeamFailureCategory | None,
    failure_reason: str | None,
    usage: TeamBudgetUsage,
    wall_seconds: float,
    team_reference: RuntimeArtifactRef,
    trusted_evidence: TrustedWorkspaceEvidence,
) -> CodingAgentRunResult:
    runtime_status = RuntimeStatus(status.value)
    effective_failure_category = (
        failure_category.value if failure_category is not None else None
    )
    effective_failure_reason = failure_reason
    worker_failure_categories = {
        result.failure_category
        for result in all_results
        if result.status is not RuntimeStatus.COMPLETED and result.failure_category
    }
    worker_failure_origins = {
        result.failure_origin
        for result in all_results
        if result.status is not RuntimeStatus.COMPLETED and result.failure_origin
    }
    if (
        failure_category is TeamFailureCategory.WORKER_RUNTIME
        and len(worker_failure_categories) == 1
    ):
        effective_failure_category = next(iter(worker_failure_categories))
    if status is TeamControlStatus.COMPLETED and not trusted_evidence.available:
        runtime_status = RuntimeStatus.FAILED
        effective_failure_category = (
            trusted_evidence.failure_code or "workspace_evidence_unavailable"
        )
        effective_failure_reason = (
            trusted_evidence.failure_reason
            or "Coordinator could not establish trusted workspace evidence."
        )
    elif status is TeamControlStatus.COMPLETED and not trusted_evidence.changed_files:
        runtime_status = RuntimeStatus.FAILED
        effective_failure_category = "no_trusted_workspace_change"
        effective_failure_reason = (
            "Team completed its DAG but produced no trusted workspace change."
        )
    base = last_result or CodingAgentRunResult(
        task_id=request.task_id,
        status=runtime_status,
        summary="Team run produced no Worker result.",
        workspace_root=request.workspace_root,
        effective_max_steps=request.effective_max_steps or request.max_steps,
        finalization_reserve_steps=request.finalization_reserve_steps or 1,
    )
    artifacts = tuple(
        [artifact for result in all_results for artifact in result.artifacts]
        + [team_reference]
    )
    data = base.model_dump()
    data.update(
        {
            "task_id": request.task_id,
            "status": runtime_status,
            "summary": (
                "Team completed all DAG nodes with coordinator-observed changes."
                if runtime_status is RuntimeStatus.COMPLETED
                else effective_failure_reason or f"Team run {status.value}."
            ),
            "workspace_root": request.workspace_root,
            "diff": trusted_evidence.diff if trusted_evidence.available else "",
            "changed_files": (
                trusted_evidence.changed_files if trusted_evidence.available else ()
            ),
            # Worker verification is a claim. AgentGrader or a future
            # coordinator-owned verifier is the trusted verification authority.
            "verification": (),
            "artifacts": artifacts,
            "checkpoint_ids": tuple(
                dict.fromkeys(
                    checkpoint
                    for result in all_results
                    for checkpoint in result.checkpoint_ids
                )
            ),
            "patch_attempts": sum(result.patch_attempts for result in all_results),
            "steps_used": usage.steps,
            "tool_calls_used": usage.tool_calls,
            "repair_attempts": usage.repairs,
            "protocol_repairs_used": usage.protocol_repairs,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": usage.cost_usd,
            "duration_ms": int(wall_seconds * 1000),
            "model_duration_ms": sum(
                result.model_duration_ms for result in all_results
            ),
            "tool_duration_ms": sum(
                result.tool_duration_ms for result in all_results
            ),
            "repair_duration_ms": sum(
                result.repair_duration_ms for result in all_results
            ),
            "declared_tool_calls": sum(
                result.declared_tool_calls for result in all_results
            ),
            "processed_tool_calls": sum(
                result.processed_tool_calls for result in all_results
            ),
            "rejected_tool_calls": sum(
                result.rejected_tool_calls for result in all_results
            ),
            "messages": tuple(
                message for result in all_results for message in result.messages
            ),
            "model_outputs": tuple(
                output for result in all_results for output in result.model_outputs
            ),
            "model_requests": tuple(
                request_evidence
                for result in all_results
                for request_evidence in result.model_requests
            ),
            "events": tuple(
                event for result in all_results for event in result.events
            ),
            "failure_category": effective_failure_category,
            "failure_origin": (
                next(iter(worker_failure_origins))
                if runtime_status is not RuntimeStatus.COMPLETED
                and len(worker_failure_origins) == 1
                else (
                    "team_runtime"
                    if runtime_status is not RuntimeStatus.COMPLETED
                    else None
                )
            ),
            "error": effective_failure_reason,
        }
    )
    return CodingAgentRunResult.model_validate(data)
