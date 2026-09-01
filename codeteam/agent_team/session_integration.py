"""Adapter that rebuilds a durable Team Runtime inside SessionService.resume()."""

from __future__ import annotations

from pathlib import Path

from codeteam.agent_team.coordination import TeamStateCoordinator
from codeteam.agent_team.persistence_errors import (
    TeamStateConflictError,
    TeamStateError,
)
from codeteam.agent_team.persistence_models import (
    TEAM_STATE_SCHEMA_VERSION,
    DurableEventDraft,
)
from codeteam.agent_team.reconciliation import (
    TeamReconciliationVerdict,
    TeamStateReconciler,
)
from codeteam.agent_team.runtime_factory import TeamRuntimeFactory
from codeteam.agent_team.team_store import (
    TEAM_STATE_DB_FILENAME,
    SQLiteTeamStateStore,
)
from codeteam.session.errors import SessionRecoveryRequiredError
from codeteam.session.models import TeamStateRef
from codeteam.session.service import (
    SessionRuntimeBuildRequest,
    SessionRuntimeBuildResult,
    probe_dirty,
    probe_head,
)


class TeamSessionRuntimeBuilder:
    def __init__(
        self,
        *,
        reconciler: TeamStateReconciler | None = None,
        runtime_factory: TeamRuntimeFactory | None = None,
    ) -> None:
        self._reconciler = reconciler or TeamStateReconciler()
        self._runtime_factory = runtime_factory or TeamRuntimeFactory()

    def build(self, request: SessionRuntimeBuildRequest) -> SessionRuntimeBuildResult:
        reference = request.session.team_state
        if reference is None:
            raise SessionRecoveryRequiredError(("team_state_reference_missing",))
        if reference.db_filename != TEAM_STATE_DB_FILENAME:
            raise SessionRecoveryRequiredError(("team_database_filename_invalid",))

        store = SQLiteTeamStateStore(request.session_dir)
        try:
            snapshot = store.load(request.session.manifest.session_id)
        except TeamStateError as exc:
            raise SessionRecoveryRequiredError(
                (f"team_state_load_failed:{type(exc).__name__}",)
            ) from exc
        if reference.schema_version != TEAM_STATE_SCHEMA_VERSION:
            raise SessionRecoveryRequiredError(("team_schema_reference_unsupported",))
        if snapshot.revision < reference.acknowledged_revision:
            issue = (
                f"team_revision_behind_session:{snapshot.revision}"
                f"<{reference.acknowledged_revision}"
            )
            raise SessionRecoveryRequiredError(
                (issue,)
            )

        coordinator = TeamStateCoordinator()
        git_has_effects = False
        if request.session.worktree is not None:
            # The Session reconciler already checks path identity/drift. Here any known
            # dirty worktree or head movement is enough to block blind RUNNING replay.
            worktree_path = request.session.worktree.path
            path = Path(worktree_path)
            head = probe_head(path)
            git_has_effects = (
                probe_dirty(path)
                or head is None
                or head != request.session.worktree.last_known_head_sha
            )
        report = self._reconciler.reconcile(
            session=request.session,
            snapshot=snapshot,
            planned_runtime_id=coordinator.runtime_id,
            git_has_unreconciled_effects=git_has_effects,
        )
        if report.verdict is not TeamReconciliationVerdict.RESUMABLE:
            raise SessionRecoveryRequiredError(report.issues)

        gap = snapshot.revision - reference.acknowledged_revision
        try:
            committed = store.commit(
                report.snapshot,
                expected_revision=snapshot.revision,
                events=(
                    DurableEventDraft(
                        event_type="team.runtime_prepared",
                        payload={
                            "new_runtime_id": coordinator.runtime_id,
                            "previous_runtime_id": snapshot.previous_runtime_id,
                            "session_revision_gap": gap,
                            "recovery_actions": list(report.recovery_actions),
                        },
                    ),
                ),
            )
        except TeamStateConflictError as exc:
            raise SessionRecoveryRequiredError(("team_state_cas_conflict",)) from exc
        except TeamStateError as exc:
            raise SessionRecoveryRequiredError(
                (f"team_state_commit_failed:{type(exc).__name__}",)
            ) from exc

        try:
            runtime = self._runtime_factory.hydrate(
                snapshot=committed,
                store=store,
                coordinator=coordinator,
            )
        except Exception as exc:
            try:
                store.commit(
                    committed,
                    expected_revision=committed.revision,
                    events=(
                        DurableEventDraft(
                            event_type="team.runtime_hydrate_failed",
                            payload={"error_type": type(exc).__name__},
                        ),
                    ),
                )
            except TeamStateError as audit_exc:
                exc.add_note(
                    "durable hydrate failure audit also failed: "
                    f"{type(audit_exc).__name__}"
                )
            raise SessionRecoveryRequiredError(
                (f"team_runtime_hydrate_failed:{type(exc).__name__}",)
            ) from exc

        return SessionRuntimeBuildResult(
            runtime=runtime,
            team_state=TeamStateRef(
                schema_version=committed.schema_version,
                acknowledged_revision=committed.revision,
            ),
            event_payload={
                "team_revision": committed.revision,
                "team_runtime_id": coordinator.runtime_id,
                "team_revision_gap_reconciled": gap,
            },
        )
