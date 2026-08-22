from datetime import UTC, datetime

from codeteam.failures.models import (
    AgentErrorCode,
    AgentFailure,
    ErrorCategory,
    FailureStage,
    RecoveryAction,
)
from codeteam.session.models import RepositoryRef, Session, SessionManifest
from codeteam.task.models import create_task_spec


def test_last_failure_metadata_secrets_do_not_serialize() -> None:
    now = datetime.now(UTC)
    session = Session(
        manifest=SessionManifest(
            session_id="ses_hidden",
            repo_id="repo",
            created_at=now,
            updated_at=now,
        ),
        task=create_task_spec(task_id="task-hidden", original_request="redact"),
        provider_id="provider",
        model_id="model",
        repo=RepositoryRef(
            repo_id="repo",
            git_common_dir="/tmp/repo/.git",
            base_sha="abc123",
        ),
        last_failure=AgentFailure(
            failure_id="failure-hidden",
            task_id="task-hidden",
            category=ErrorCategory.MODEL,
            code=AgentErrorCode.MODEL_AUTH_FAILED,
            stage=FailureStage.MODEL_CALL,
            message="model failed",
            transient=False,
            retryable=False,
            recommended_recovery=RecoveryAction.STOP,
            source_message="secret token sk-hidden",
            metadata={"api_key": "sk-hidden-metadata", "nested": {"token": "secret"}},
        ),
    )

    raw = session.model_dump_json()

    assert "sk-hidden" not in raw
    assert "sk-hidden-metadata" not in raw
    assert "<redacted>" in raw
