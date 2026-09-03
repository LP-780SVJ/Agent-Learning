"""Atomic storage for node and Team run artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from codeteam.agent.runtime_models import RuntimeArtifactRef
from codeteam.agent_team.team_models import (
    NodeExecutionResult,
    TeamProgressState,
    TeamRunArtifact,
)
from codeteam.redaction import redact_sensitive_data


class TeamArtifactError(RuntimeError):
    pass


class TeamRunArtifactStore:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir.resolve(strict=True)
        self.artifact_dir = self.session_dir / "artifacts"
        if self.artifact_dir.exists() and self.artifact_dir.is_symlink():
            raise TeamArtifactError("artifact directory cannot be a symlink")
        self.artifact_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.artifact_dir, 0o700)

    def write_node_result(self, result: NodeExecutionResult) -> RuntimeArtifactRef:
        relative = Path("artifacts") / "nodes" / (
            f"{_safe_component(result.node_id)}-attempt-{result.attempt}.json"
        )
        return self._write_model(
            relative,
            _sanitized_model_json(result),
            kind="team_node_result",
            schema_version=1,
        )

    def write_team_run(self, artifact: TeamRunArtifact) -> RuntimeArtifactRef:
        return self._write_model(
            Path("artifacts") / "team_run.json",
            _sanitized_model_json(artifact),
            kind="team_run",
            schema_version=artifact.schema_version,
        )

    def write_progress(self, progress: TeamProgressState) -> RuntimeArtifactRef:
        return self._write_model(
            Path("artifacts") / "team_progress.json",
            _sanitized_model_json(progress),
            kind="team_progress",
            schema_version=progress.schema_version,
        )

    def load_progress(self) -> TeamProgressState:
        target = self._safe_target(Path("artifacts") / "team_progress.json")
        if target.is_symlink() or not target.is_file():
            raise TeamArtifactError("Team progress state is missing or unsafe")
        return TeamProgressState.model_validate_json(target.read_bytes())

    def load_node_result(self, reference: RuntimeArtifactRef) -> NodeExecutionResult:
        if reference.kind != "team_node_result":
            raise TeamArtifactError("artifact is not a Team node result")
        raw = self._read_verified(reference)
        return NodeExecutionResult.model_validate_json(raw)

    def _write_model(
        self,
        relative: Path,
        content: str,
        *,
        kind: str,
        schema_version: int,
    ) -> RuntimeArtifactRef:
        target = self._safe_target(relative)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.exists() and target.is_symlink():
            raise TeamArtifactError("artifact target cannot be a symlink")
        payload = (content + "\n").encode("utf-8")
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                os.chmod(temporary, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return RuntimeArtifactRef(
            kind=kind,
            session_id=self.session_dir.name,
            path=relative,
            schema_version=schema_version,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def _read_verified(self, reference: RuntimeArtifactRef) -> bytes:
        target = self._safe_target(reference.path)
        if target.is_symlink() or not target.is_file():
            raise TeamArtifactError("artifact file is missing or unsafe")
        payload = target.read_bytes()
        if hashlib.sha256(payload).hexdigest() != reference.sha256:
            raise TeamArtifactError("artifact hash mismatch")
        return payload

    def _safe_target(self, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise TeamArtifactError("artifact path escapes the Session directory")
        target = self.session_dir / relative
        resolved_parent = target.parent.resolve()
        try:
            resolved_parent.relative_to(self.session_dir)
        except ValueError as error:
            raise TeamArtifactError(
                "artifact path escapes the Session directory"
            ) from error
        return target


def _safe_component(value: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in value)
    return safe.strip("-") or "node"


def _sanitized_model_json(model: BaseModel) -> str:
    sanitized = redact_sensitive_data(model.model_dump(mode="json", by_alias=True))
    return json.dumps(sanitized, ensure_ascii=False, indent=2)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
