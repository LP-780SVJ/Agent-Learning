"""codeteam.session — Durable Session 持久化与恢复。"""
from codeteam.session.errors import (
    CheckpointMissingError,
    ProviderUnavailableError,
    RepositoryMismatchError,
    SessionAlreadyActiveError,
    SessionAlreadyExistsError,
    SessionCorruptedError,
    SessionError,
    SessionNotFoundError,
    SessionSchemaUnsupportedError,
    SessionTerminalError,
    WorktreeMissingError,
)
from codeteam.session.models import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    ActiveOperation,
    ContextMetadata,
    OperationStatus,
    RepositoryRef,
    Session,
    SessionEvent,
    SessionManifest,
    SessionStatus,
    SessionUsage,
    WorktreeRef,
)
from codeteam.session.store import (
    DEFAULT_SESSIONS_DIR_NAME,
    JsonSessionStore,
)

__all__ = [
    "DEFAULT_SESSIONS_DIR_NAME",
    "JsonSessionStore",
    # errors
    "SessionError", "SessionNotFoundError", "SessionCorruptedError",
    "SessionSchemaUnsupportedError", "SessionAlreadyExistsError",
    "SessionAlreadyActiveError", "SessionTerminalError",
    "RepositoryMismatchError", "WorktreeMissingError",
    "CheckpointMissingError", "ProviderUnavailableError",
    # models
    "CURRENT_SCHEMA_VERSION", "SUPPORTED_SCHEMA_VERSIONS",
    "Session", "SessionStatus", "SessionManifest", "SessionEvent",
    "SessionUsage", "RepositoryRef", "WorktreeRef",
    "ActiveOperation", "OperationStatus", "ContextMetadata",
]