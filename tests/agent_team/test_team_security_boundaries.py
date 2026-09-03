from __future__ import annotations

import json
import subprocess
from pathlib import Path

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
    ModelOutputEvidence,
    RuntimeStatus,
    VerificationEvidence,
)
from codeteam.agent_team.mailbox import AgentMessage, AgentMessageType
from codeteam.agent_team.models import AgentRole, WorkerAssignment
from codeteam.agent_team.scheduler import TaskClaim
from codeteam.agent_team.team_artifacts import TeamRunArtifactStore
from codeteam.agent_team.team_models import (
    NodeBudgetAllocation,
    NodeExecutionResult,
    NodeTiming,
)
from codeteam.agent_team.team_planning import DeterministicSingleNodePlanner
from codeteam.agent_team.team_runtime_provider import LocalTeamRuntimeProvider
from codeteam.agent_team.worker_executor import (
    WorkerExecutionRequest,
    WorkerExecutor,
)
from codeteam.agent_team.workspace_evidence import (
    capture_git_metadata_baseline,
    collect_trusted_workspace_evidence,
)
from codeteam.redaction import REDACTED, redact_sensitive_data
from codeteam.schemas.messages import Message


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        shell=False,
        timeout=10,
        check=True,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "CodeTeam Tests")
    _git(root, "config", "user.email", "codeteam-tests@example.invalid")
    (root / "app.py").write_text("VALUE = 0\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-qm", "baseline")
    return root


def _execution_request(root: Path) -> WorkerExecutionRequest:
    assignment = WorkerAssignment(
        assignment_id="node-1",
        task_id="task-1",
        source_step_id="node-1",
        role=AgentRole.BACKEND,
        goal="Implement the change.",
        expected_output="A patch.",
        budget_weight=1,
    )
    return WorkerExecutionRequest(
        parent_request=CodingAgentRunRequest(
            task_id="task-1",
            task="Implement the change.",
            workspace_root=root,
            provider_id="scripted",
            model_id="scripted",
        ),
        assignment=assignment,
        claim=TaskClaim(
            node_id="node-1",
            worker_id="worker-backend-1",
            attempt=1,
            claimed_at=1.0,
            runtime_id="runtime-1",
            worker_generation=1,
        ),
        workspace_root=root,
        budget=NodeBudgetAllocation(
            node_id="node-1",
            weight=1,
            max_steps=5,
            max_tool_calls=8,
            max_repairs=1,
            max_protocol_repairs=1,
        ),
        ready_at=0.5,
    )


def test_redaction_recurses_without_changing_non_secret_diagnostics() -> None:
    raw = {
        "api_key": "api-key-value",
        "nested": [
            {"Authorization": "Bearer authorization-value"},
            ("password=password-value", "ordinary timeout detail"),
        ],
        "max_output_tokens": 4096,
    }

    safe = redact_sensitive_data(raw)

    assert safe["api_key"] == REDACTED
    assert safe["nested"][0]["Authorization"] == REDACTED
    assert safe["nested"][1][0] == "password=<redacted>"
    assert safe["nested"][1][1] == "ordinary timeout detail"
    assert safe["max_output_tokens"] == 4096


def test_redaction_preserves_source_code_and_token_domain_language() -> None:
    source = (
        'token = request.get("refresh_token", "")\n'
        'token=request.get("refresh_token", "")\n'
        "# Map token-specific errors at the API boundary.\n"
    )

    assert redact_sensitive_data(source) == source
    assert redact_sensitive_data("api_key=actual-secret-value") == (
        "api_key=<redacted>"
    )
    assert redact_sensitive_data("credential-marker-for-redaction-test") == REDACTED


def test_worker_result_and_artifact_are_sanitized_without_changing_retry_logic(
    tmp_path: Path,
) -> None:
    secret_values = (
        "sk-provider-secret-12345",
        "password-value-12345",
        "credential-value-12345",
    )

    class SensitiveFailureRuntime:
        def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
            return CodingAgentRunResult(
                task_id=request.task_id,
                status=RuntimeStatus.FAILED,
                summary=f"Authorization: Bearer {secret_values[0]}",
                workspace_root=request.workspace_root,
                verification=(
                    VerificationEvidence(
                        argv=("pytest",),
                        passed=False,
                        stdout=f"password={secret_values[1]}",
                        stderr=f"credential={secret_values[2]}",
                    ),
                ),
                messages=(
                    Message(role="assistant", content=f"secret={secret_values[0]}"),
                ),
                model_outputs=(
                    ModelOutputEvidence(step=1, raw_content=secret_values[0]),
                ),
                events=(f"credential-{secret_values[2]}",),
                failure_category="timeout",
                error=f"api_key={secret_values[0]}",
            )

    root = _repo(tmp_path)
    result = WorkerExecutor(SensitiveFailureRuntime()).execute(
        _execution_request(root)
    )
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    store = TeamRunArtifactStore(session_dir)
    reference = store.write_node_result(result)
    payload = (session_dir / reference.path).read_text(encoding="utf-8")

    assert result.retryable is True
    assert result.failure_category == "timeout"
    assert result.runtime_result is not None
    assert all(value not in payload for value in secret_values)
    assert "ordinary timeout" not in payload
    assert "<redacted>" in payload
    assert store.load_node_result(reference).failure_category == "timeout"


def test_unexpected_exception_keeps_structured_safe_diagnostics(tmp_path: Path) -> None:
    class RaisingRuntime:
        def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
            del request
            raise RuntimeError("token=unsafe-value")

    result = WorkerExecutor(RaisingRuntime()).execute(
        _execution_request(_repo(tmp_path))
    )

    assert result.failure_category == "worker_runtime_failure"
    assert result.error_code == "worker_runtime_failure"
    assert result.exception_type == "RuntimeError"
    assert result.error_summary_sha256 is not None
    assert len(result.error_summary_sha256) == 64
    assert result.error == "RuntimeError: token=<redacted>"


def test_trusted_workspace_evidence_uses_real_tracked_and_untracked_text(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "new_file.py").write_text("NEW = True\n", encoding="utf-8")

    evidence = collect_trusted_workspace_evidence(root)

    assert evidence.available is True
    assert evidence.changed_files == ("app.py", "new_file.py")
    assert "-VALUE = 0" in evidence.diff
    assert "+VALUE = 1" in evidence.diff
    assert "+NEW = True" in evidence.diff


def test_untracked_binary_and_escape_symlink_fail_closed(tmp_path: Path) -> None:
    binary_root = _repo(tmp_path / "binary")
    (binary_root / "payload.bin").write_bytes(b"abc\0def")

    binary = collect_trusted_workspace_evidence(binary_root)

    assert binary.available is False
    assert binary.changed_files == ()
    assert binary.diff == ""
    assert binary.failure_code == "workspace_evidence_unavailable"

    symlink_root = _repo(tmp_path / "symlink")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (symlink_root / "escape.txt").symlink_to(outside)

    escaped = collect_trusted_workspace_evidence(symlink_root)

    assert escaped.available is False
    assert escaped.changed_files == ()
    assert "escapes workspace" in (escaped.failure_reason or "")


def test_git_metadata_change_is_rejected_against_pre_execution_baseline(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    baseline = capture_git_metadata_baseline(root)
    with (root / ".git/config").open("a", encoding="utf-8") as handle:
        handle.write("\n# unauthorized metadata mutation\n")
    (root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    evidence = collect_trusted_workspace_evidence(
        root,
        git_metadata_baseline=baseline,
    )

    assert evidence.available is False
    assert evidence.failure_code == "git_metadata_changed"
    assert evidence.changed_files == ()
    assert evidence.diff == ""


def test_artifact_schema_labels_worker_claims_as_untrusted(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    result = NodeExecutionResult(
        node_id="node-1",
        worker_id="worker-1",
        runtime_id="runtime-1",
        worker_generation=1,
        attempt=1,
        status=RuntimeStatus.COMPLETED,
        runtime_result=CodingAgentRunResult(
            task_id="child",
            status=RuntimeStatus.COMPLETED,
            summary="worker claim",
            workspace_root=tmp_path,
            changed_files=("claimed.py",),
        ),
        timing=NodeTiming(ready_at=0.0, started_at=0.0, finished_at=0.0),
    )

    reference = TeamRunArtifactStore(session_dir).write_node_result(result)
    payload = json.loads((session_dir / reference.path).read_text(encoding="utf-8"))

    assert "worker_reported_result" in payload
    assert "runtime_result" not in payload


def test_durable_mailbox_and_event_payloads_are_sanitized(tmp_path: Path) -> None:
    secret = "credential-mailbox-value-12345"
    root = _repo(tmp_path)
    request = CodingAgentRunRequest(
        task_id="task-mailbox",
        task="Inspect mailbox redaction.",
        workspace_root=root,
        provider_id="scripted",
        model_id="scripted",
    )
    plan = DeterministicSingleNodePlanner().plan(request)
    handle = LocalTeamRuntimeProvider(tmp_path / "state").create(
        request=request,
        plan=plan,
    )
    handle.runtime.send_message(
        AgentMessage(
            message_id="message-sensitive",
            sender_id="worker-backend-1",
            recipient_id=handle.lead_id,
            message_type=AgentMessageType.INFO,
            task_id=request.task_id,
            correlation_id="redaction-check",
            payload={"nested": [{"credential": secret}]},
        )
    )
    handle.runtime.persist(
        event_type="team.sensitive_test",
        payload={"detail": f"Authorization: Bearer {secret}"},
    )

    snapshot_json = handle.runtime.snapshot.model_dump_json()
    events_json = "".join(
        event.model_dump_json()
        for event in handle.store.load_events(handle.session_id)
    )
    assert secret not in snapshot_json
    assert secret not in events_json
    assert "<redacted>" in snapshot_json
    assert "<redacted>" in events_json
