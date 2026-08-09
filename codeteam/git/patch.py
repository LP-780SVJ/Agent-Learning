from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from codeteam.git.errors import PatchParseError, PatchSecurityError
from codeteam.git.models import PatchResult, PatchStatus

DEFAULT_MAX_PATCH_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_FILES = 50
DEFAULT_TIMEOUT_SECONDS = 10.0


def validate_patch_path(root: Path, path_text: str) -> Path:
    """验证 Patch 中的路径是否安全，并返回绝对路径。
    """
    if not path_text:
        raise PatchSecurityError("Patch path cannot be empty.")

    posix_path = PurePosixPath(path_text)
    windows_path = PureWindowsPath(path_text)

    if posix_path.is_absolute() or windows_path.is_absolute():
        raise PatchSecurityError(
            f"Absolute patch path rejected: {path_text!r}"
        )

    if windows_path.drive:
        raise PatchSecurityError(
            f"Windows drive path rejected: {path_text!r}"
        )

    posix_first = posix_path.parts[0] if posix_path.parts else ""
    windows_first = windows_path.parts[0] if windows_path.parts else ""

    if posix_first == ".git" or windows_first.casefold() == ".git":
        raise PatchSecurityError("Patch cannot modify .git metadata.")

    canonical_root = root.resolve(strict=True)
    target = (canonical_root / path_text).resolve(strict=False)

    if not target.is_relative_to(canonical_root):
        raise PatchSecurityError(
            f"Patch path escapes repository: {path_text!r}"
        )

    return target

def extract_patch_paths(root: Path, patch: bytes) -> list[str]:
    """从 Patch 中提取所有路径，并验证它们的安全性。
    """
    try:
        result = subprocess.run(
            ["git", "apply", "--numstat", "-z", "-"],
            cwd=root,
            input=patch,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise PatchParseError("Patch path extraction timed out.") from error

    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace")
        raise PatchParseError(message or "Unable to parse patch paths.")

    return parse_numstat_paths(result.stdout)

def parse_numstat_paths(
    data: bytes,
) -> list[str]:
    """解析 git apply --numstat -z 的输出，提取所有路径。"""
    paths: list[str] = []

    cursor = 0

    while cursor < len(data):
        tab1 = data.index(b"\t", cursor)
        tab2 = data.index(b"\t", tab1 + 1)

        path_end = data.index(
            b"\0",
            tab2 + 1,
        )

        first_path = data[
            tab2 + 1:path_end
        ]

        cursor = path_end + 1

        if first_path:
            paths.append(
                os.fsdecode(first_path)
            )
            continue

        # Rename / Copy
        old_end = data.index(
            b"\0",
            cursor,
        )

        old_path = data[
            cursor:old_end
        ]

        cursor = old_end + 1

        new_end = data.index(
            b"\0",
            cursor,
        )

        new_path = data[
            cursor:new_end
        ]

        cursor = new_end + 1

        paths.append(
            os.fsdecode(old_path)
        )
        paths.append(
            os.fsdecode(new_path)
        )

    return list(dict.fromkeys(paths))

class PatchValidator:
    """验证和应用 Git Patch 的工具类。
    变量说明：
    - root：Git 仓库的根目录
    - max_patch_bytes：允许的最大 Patch 字节数
    - max_files：允许的最大文件数量
    """
    def __init__(
        self,
        root: Path | str,
        *,
        max_patch_bytes: int = DEFAULT_MAX_PATCH_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self.root = Path(root).resolve(strict=True)

        if not self.root.is_dir():
            raise ValueError("Repository root must be a directory.")
        if max_patch_bytes <= 0 or max_files <= 0:
            raise ValueError("Patch limits must be positive.")

        self.max_patch_bytes = max_patch_bytes
        self.max_files = max_files

    def validate(self, patch: str) -> PatchResult:
        """验证 Patch 的安全性和可应用性。"""
        patch_bytes = patch.encode("utf-8")
        digest = hashlib.sha256(patch_bytes).hexdigest()

        if not patch_bytes.strip():
            return PatchResult(
                status=PatchStatus.CHECK_FAILED,
                patch_sha256=digest,
                affected_paths=[],
                failure_reason="Patch is empty.",
            )

        if len(patch_bytes) > self.max_patch_bytes:
            return PatchResult(
                status=PatchStatus.SECURITY_REJECTED,
                patch_sha256=digest,
                affected_paths=[],
                failure_reason="Patch exceeds size limit.",
            )

        if b"GIT binary patch" in patch_bytes.splitlines():
            return PatchResult(
                status=PatchStatus.SECURITY_REJECTED,
                patch_sha256=digest,
                affected_paths=[],
                failure_reason="Binary patches are disabled.",
            )

        try:
            paths = extract_patch_paths(self.root, patch_bytes)
        except PatchParseError as error:
            return PatchResult(
                status=PatchStatus.CHECK_FAILED,
                patch_sha256=digest,
                affected_paths=[],
                failure_reason=str(error),
            )

        if not paths:
            return PatchResult(
                status=PatchStatus.CHECK_FAILED,
                patch_sha256=digest,
                affected_paths=[],
                failure_reason="Patch contains no file changes.",
            )

        if len(paths) > self.max_files:
            return PatchResult(
                status=PatchStatus.SECURITY_REJECTED,
                patch_sha256=digest,
                affected_paths=paths,
                failure_reason="Patch touches too many files.",
            )

        try:
            for path in paths:
                validate_patch_path(self.root, path)
        except PatchSecurityError as error:
            return PatchResult(
                status=PatchStatus.SECURITY_REJECTED,
                patch_sha256=digest,
                affected_paths=paths,
                failure_reason=str(error),
            )

        try:
            result = subprocess.run(
                ["git", "apply", "--check", "-"],
                cwd=self.root,
                input=patch_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return PatchResult(
                status=PatchStatus.CHECK_FAILED,
                patch_sha256=digest,
                affected_paths=paths,
                failure_reason="git apply --check timed out.",
            )

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        if result.returncode != 0:
            return PatchResult(
                status=PatchStatus.CHECK_FAILED,
                patch_sha256=digest,
                affected_paths=paths,
                stdout=stdout,
                stderr=stderr,
                failure_reason="git apply --check failed.",
            )

        return PatchResult(
            status=PatchStatus.VALID,
            patch_sha256=digest,
            affected_paths=paths,
            stdout=stdout,
            stderr=stderr,
            applied=False,
        )