from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

from codeteam.git.diff import (
    parse_name_status,
    parse_nul_paths,
    parse_numstat_summary,
)
from codeteam.git.errors import (
    GitCommandError,
    GitWorkspaceError,
    NotGitRepositoryError,
)
from codeteam.git.models import (
    GitChange,
    GitChangeKind,
    GitDiff,
    PatchResult,
    PatchStatus,
)
from codeteam.git.patch import PatchValidator

DEFAULT_GIT_TIMEOUT_SECONDS = 10.0


def _workspace_entry_digest(path: Path) -> str:
    """Hash one managed path without following a symlink target."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "missing"
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode):
        payload = f"symlink\0{mode:o}\0{os.readlink(path)}".encode(
            "utf-8", errors="surrogateescape"
        )
        return hashlib.sha256(payload).hexdigest()
    if stat.S_ISREG(metadata.st_mode):
        digest = hashlib.sha256(f"file\0{mode:o}\0".encode())
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as error:
            return f"changed-during-fingerprint:{error.errno}"
        with os.fdopen(descriptor, "rb") as file:
            opened = os.fstat(file.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
            ):
                return "changed-during-fingerprint"
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    return hashlib.sha256(
        f"other\0{stat.S_IFMT(metadata.st_mode):o}\0{mode:o}".encode()
    ).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def snapshot_paths(
    root: Path,
    paths: list[str],
) -> dict[str, str | None]:
    return {
        path: sha256_file(root / path)
        for path in paths
    }

class GitWorkspace:
    def __init__(self, root: Path | str) -> None:
        requested_root = Path(root).resolve(strict=True)

        if not requested_root.is_dir():
            raise ValueError("Git workspace root must be a directory.")

        try:
            result = subprocess.run(  # noqa: UP022
                ["git", "rev-parse", "--show-toplevel"],
                cwd=requested_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise NotGitRepositoryError(
                "Timed out while locating Git repository."
            ) from error

        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace")
            raise NotGitRepositoryError(
                message or f"Not a Git repository: {requested_root}"
            )

        root_text = os.fsdecode(result.stdout.rstrip(b"\n"))
        self.root = Path(root_text).resolve(strict=True)
        self.validator = PatchValidator(self.root)

    def _run_git(self, args: list[str]) -> bytes:
        """封装git命令"""
        try:
            result = subprocess.run(  # noqa: UP022
                ["git", *args],
                cwd=self.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandError(
                f"Git command timed out: git {' '.join(args)}"
            ) from error

        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace")
            raise GitCommandError(
                message or f"Git command failed: git {' '.join(args)}"
            )

        return result.stdout

    def _tracked_changes(
        self,
        base_ref: str,
    ) -> list[GitChange]:
        output = self._run_git(
            [
                "diff",
                "--name-status",
                "--find-renames=50%",
                "-z",
                base_ref,
                "--",
            ]
        )
        return parse_name_status(output)

    def _untracked_paths(self) -> list[str]:
        output = self._run_git(
            [
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ]
        )
        return parse_nul_paths(output)

    def changed_files(
        self,
        base_ref: str = "HEAD",
    ) -> list[GitChange]:
        _validate_base_ref(base_ref)

        tracked = self._tracked_changes(base_ref)
        untracked = self._untracked_paths()

        return [
            *tracked,
            *[
                GitChange(
                    kind=GitChangeKind.UNTRACKED,
                    path=path,
                )
                for path in untracked
            ],
        ]

    def content_fingerprint(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        """Fingerprint tracked and non-ignored untracked workspace content."""

        paths = parse_nul_paths(
            self._run_git(
                ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
            )
        )
        entries = tuple(
            (path, _workspace_entry_digest(self.root / path))
            for path in sorted(set(paths))
        )
        serialized = "\n".join(f"{path}\0{digest}" for path, digest in entries)
        return hashlib.sha256(serialized.encode()).hexdigest(), entries

    def diff(self, base_ref: str = "HEAD") -> GitDiff:
        _validate_base_ref(base_ref)

        patch_bytes = self._run_git(
            [
                "diff",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--find-renames=50%",
                "--src-prefix=a/",
                "--dst-prefix=b/",
                base_ref,
                "--",
            ]
        )

        numstat_bytes = self._run_git(
            [
                "diff",
                "--numstat",
                "--find-renames=50%",
                "-z",
                base_ref,
                "--",
            ]
        )

        tracked = self._tracked_changes(base_ref)
        untracked = self._untracked_paths()
        additions, deletions, has_binary = parse_numstat_summary(
            numstat_bytes
        )

        untracked_changes = [
            GitChange(
                kind=GitChangeKind.UNTRACKED,
                path=path,
            )
            for path in untracked
        ]

        return GitDiff(
            base_ref=base_ref,
            patch=patch_bytes.decode("utf-8", errors="replace"),
            changes=[*tracked, *untracked_changes],
            untracked_paths=untracked,
            additions=additions,
            deletions=deletions,
            has_binary_changes=has_binary,
            patch_bytes=len(patch_bytes),
        )

    def check_patch(self, patch: str) -> PatchResult:
        return self.validator.validate(patch)

    def apply_patch(self, patch: str) -> PatchResult:
        validation = self.check_patch(patch)

        if validation.status != PatchStatus.VALID:
            return validation

        before = snapshot_paths(
            self.root,
            validation.affected_paths,
        )
        patch_bytes = patch.encode("utf-8")

        try:
            result = subprocess.run(  # noqa: UP022
                ["git", "apply", "-"],
                cwd=self.root,
                input=patch_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._verify_failed_apply(
                validation.affected_paths,
                before,
            )
            return PatchResult(
                status=PatchStatus.APPLY_FAILED,
                patch_sha256=validation.patch_sha256,
                affected_paths=validation.affected_paths,
                applied=False,
                failure_reason="git apply timed out.",
            )

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        if result.returncode != 0:
            self._verify_failed_apply(
                validation.affected_paths,
                before,
            )
            return PatchResult(
                status=PatchStatus.APPLY_FAILED,
                patch_sha256=validation.patch_sha256,
                affected_paths=validation.affected_paths,
                stdout=stdout,
                stderr=stderr,
                applied=False,
                failure_reason="git apply failed.",
            )

        return PatchResult(
            status=PatchStatus.APPLIED,
            patch_sha256=validation.patch_sha256,
            affected_paths=validation.affected_paths,
            stdout=stdout,
            stderr=stderr,
            applied=True,
        )

    def _verify_failed_apply(
        self,
        paths: list[str],
        before: dict[str, str | None],
    ) -> None:
        after = snapshot_paths(self.root, paths)

        if before != after:
            raise GitWorkspaceError(
                "CRITICAL: failed git apply changed workspace state."
            )

def _validate_base_ref(base_ref: str) -> None:
    """验证 base_ref 是否有效"""
    if (
        not base_ref
        or base_ref.startswith("-")
        or "\0" in base_ref
    ):
        raise ValueError(f"Invalid Git base ref: {base_ref!r}")
