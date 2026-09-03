"""Coordinator-owned workspace evidence for Team Coding Runtime results."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from codeteam.agent.editing import FileEdit, file_edits_to_patch, validate_edit_path
from codeteam.git.errors import GitWorkspaceError
from codeteam.git.models import GitChangeKind
from codeteam.git.workspace import GitWorkspace
from codeteam.redaction import redact_sensitive_text

MAX_UNTRACKED_TEXT_BYTES = 1_000_000


class TrustedWorkspaceEvidence(BaseModel):
    """Evidence observed by the coordinator, never copied from a Worker claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    changed_files: tuple[str, ...] = ()
    diff: str = ""
    failure_code: str | None = None
    failure_reason: str | None = None


class GitMetadataBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: bool
    fingerprint: str | None = None
    failure_reason: str | None = None


def capture_git_metadata_baseline(workspace_root: Path) -> GitMetadataBaseline:
    """Fingerprint security-relevant Git metadata without hashing mutable index caches."""

    try:
        requested_root = workspace_root.resolve(strict=True)
        workspace = GitWorkspace(requested_root)
        if workspace.root != requested_root:
            raise ValueError("workspace_root must be the Git repository root")
        git_marker = requested_root / ".git"
        roots: list[Path] = []
        entries: list[tuple[str, bytes]] = []
        if git_marker.is_dir():
            roots.append(git_marker.resolve(strict=True))
        elif git_marker.is_file():
            marker = git_marker.read_bytes()
            entries.append((".git", marker))
            prefix = b"gitdir: "
            if not marker.startswith(prefix):
                raise ValueError("worktree .git file has an invalid format")
            git_dir = Path(os.fsdecode(marker[len(prefix) :].strip()))
            if not git_dir.is_absolute():
                git_dir = git_marker.parent / git_dir
            git_dir = git_dir.resolve(strict=True)
            roots.append(git_dir)
            common_marker = git_dir / "commondir"
            if common_marker.is_file():
                common = Path(common_marker.read_text(encoding="utf-8").strip())
                if not common.is_absolute():
                    common = git_dir / common
                roots.append(common.resolve(strict=True))
        else:
            raise ValueError("Git metadata marker is missing")

        for index, git_root in enumerate(dict.fromkeys(roots)):
            for name in ("HEAD", "config", "packed-refs"):
                target = git_root / name
                if target.exists():
                    entries.append((f"git-{index}/{name}", _read_metadata_file(target)))
            refs = git_root / "refs"
            if refs.exists():
                for target in sorted(refs.rglob("*")):
                    if target.is_file():
                        relative = target.relative_to(git_root).as_posix()
                        entries.append(
                            (f"git-{index}/{relative}", _read_metadata_file(target))
                        )
        digest = hashlib.sha256()
        for name, payload in sorted(entries):
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(payload)
            digest.update(b"\0")
        return GitMetadataBaseline(available=True, fingerprint=digest.hexdigest())
    except (GitWorkspaceError, OSError, UnicodeError, ValueError) as error:
        return GitMetadataBaseline(
            available=False,
            failure_reason=redact_sensitive_text(
                f"{type(error).__name__}: {error}"
            ),
        )


def collect_trusted_workspace_evidence(
    workspace_root: Path,
    *,
    git_metadata_baseline: GitMetadataBaseline | None = None,
) -> TrustedWorkspaceEvidence:
    """Collect safe Git evidence or return a structured fail-closed result."""

    try:
        if git_metadata_baseline is not None:
            current_metadata = capture_git_metadata_baseline(workspace_root)
            if not git_metadata_baseline.available or not current_metadata.available:
                raise ValueError("Git metadata could not be verified")
            if current_metadata.fingerprint != git_metadata_baseline.fingerprint:
                return TrustedWorkspaceEvidence(
                    available=False,
                    failure_code="git_metadata_changed",
                    failure_reason=(
                        "Security-relevant .git metadata changed during Team execution."
                    ),
                )
        requested_root = workspace_root.resolve(strict=True)
        workspace = GitWorkspace(requested_root)
        if workspace.root != requested_root:
            raise ValueError("workspace_root must be the Git repository root")
        changes = workspace.changed_files()
        for change in changes:
            _validate_change_path(workspace.root, change.path, change.kind)
            if change.old_path is not None:
                _validate_change_path(
                    workspace.root,
                    change.old_path,
                    GitChangeKind.DELETED,
                )
        diff = workspace.diff()
        chunks = [diff.patch]
        for path in diff.untracked_paths:
            content = _read_untracked_text(workspace.root, path)
            chunks.append(
                file_edits_to_patch(
                    workspace.root,
                    [FileEdit(path=path, content=content)],
                    assume_missing_paths=frozenset({path}),
                )
            )
        return TrustedWorkspaceEvidence(
            available=True,
            changed_files=tuple(dict.fromkeys(change.path for change in changes)),
            diff="".join(chunks),
        )
    except (GitWorkspaceError, OSError, UnicodeError, ValueError) as error:
        return TrustedWorkspaceEvidence(
            available=False,
            failure_code="workspace_evidence_unavailable",
            failure_reason=redact_sensitive_text(
                f"{type(error).__name__}: {error}"
            ),
        )


def _validate_change_path(
    root: Path,
    path: str,
    kind: GitChangeKind,
) -> None:
    validate_edit_path(path)
    target = root / path
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Git change path escapes workspace: {path}") from error
    if kind is GitChangeKind.UNTRACKED and target.is_symlink():
        raise ValueError(f"untracked symlink is not trusted evidence: {path}")


def _read_untracked_text(root: Path, path: str) -> str:
    _validate_change_path(root, path, GitChangeKind.UNTRACKED)
    target = root / path
    metadata = target.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"untracked evidence must be a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise ValueError(f"untracked file changed while reading: {path}")
        payload = os.read(descriptor, MAX_UNTRACKED_TEXT_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(payload) > MAX_UNTRACKED_TEXT_BYTES:
        raise ValueError(f"untracked text exceeds evidence size limit: {path}")
    if b"\0" in payload:
        raise ValueError(f"untracked binary content is not trusted evidence: {path}")
    return payload.decode("utf-8")


def _read_metadata_file(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError(f"Git metadata entry is not a regular file: {path.name}")
    if metadata.st_size > MAX_UNTRACKED_TEXT_BYTES:
        raise ValueError(f"Git metadata entry is unexpectedly large: {path.name}")
    return path.read_bytes()
