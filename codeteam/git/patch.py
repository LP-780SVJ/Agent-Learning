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
        result = subprocess.run(  # noqa: UP022
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

    return _dedupe_paths(
        [
            *parse_rename_copy_header_paths(patch),
            *parse_numstat_paths(result.stdout),
        ]
    )


def parse_rename_copy_header_paths(patch: bytes) -> list[str]:
    """从 rename/copy header 中补充 old/new 两侧路径。"""
    paths: list[str] = []
    source_path: str | None = None
    target_prefix: bytes | None = None

    for line in patch.splitlines():
        if line.startswith(b"diff --git "):
            source_path = None
            target_prefix = None
            continue

        if line.startswith(b"rename from "):
            source_path = decode_git_patch_path(line[len(b"rename from "):])
            target_prefix = b"rename to "
            continue

        if line.startswith(b"copy from "):
            source_path = decode_git_patch_path(line[len(b"copy from "):])
            target_prefix = b"copy to "
            continue

        if (
            source_path is not None
            and target_prefix is not None
            and line.startswith(target_prefix)
        ):
            target_path = decode_git_patch_path(line[len(target_prefix):])
            paths.append(source_path)
            paths.append(target_path)
            source_path = None
            target_prefix = None
            continue

    return paths


def decode_git_patch_path(path_token: bytes) -> str:
    """解码 Git patch header 中可能出现的 C-style quoted 路径。"""
    token = path_token.strip()

    if not token:
        raise PatchParseError("Patch path cannot be empty.")

    if token.startswith(b'"'):
        if not token.endswith(b'"') or len(token) == 1:
            raise PatchParseError("Malformed quoted patch path.")
        return os.fsdecode(_decode_c_quoted_bytes(token[1:-1]))

    return os.fsdecode(token)


def _decode_c_quoted_bytes(data: bytes) -> bytes:
    decoded = bytearray()
    cursor = 0

    while cursor < len(data):
        byte = data[cursor]

        if byte != ord("\\"):
            decoded.append(byte)
            cursor += 1
            continue

        cursor += 1
        if cursor >= len(data):
            raise PatchParseError("Malformed quoted patch path.")

        escaped = data[cursor]

        if ord("0") <= escaped <= ord("7"):
            octal = bytearray([escaped])
            cursor += 1
            while (
                cursor < len(data)
                and len(octal) < 3
                and ord("0") <= data[cursor] <= ord("7")
            ):
                octal.append(data[cursor])
                cursor += 1
            decoded.append(int(octal.decode("ascii"), 8))
            continue

        escape_map = {
            ord("a"): b"\a",
            ord("b"): b"\b",
            ord("f"): b"\f",
            ord("n"): b"\n",
            ord("r"): b"\r",
            ord("t"): b"\t",
            ord("v"): b"\v",
            ord("\\"): b"\\",
            ord('"'): b'"',
        }

        if escaped not in escape_map:
            raise PatchParseError("Unsupported quoted patch path escape.")

        decoded.extend(escape_map[escaped])
        cursor += 1

    return bytes(decoded)

def parse_numstat_paths(
    data: bytes,
) -> list[str]:
    """解析 git apply --numstat -z 的输出，提取所有路径。"""
    paths: list[str] = []

    cursor = 0

    try:
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

            # Some numstat -z producers encode rename/copy as:
            # additions<TAB>deletions<TAB>NUL old-path NUL new-path NUL.
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

            if not old_path or not new_path:
                raise PatchParseError("Malformed rename/copy numstat output.")

            paths.append(
                os.fsdecode(old_path)
            )
            paths.append(
                os.fsdecode(new_path)
            )
    except ValueError as error:
        raise PatchParseError("Malformed git numstat output.") from error

    return _dedupe_paths(paths)


def _dedupe_paths(paths: list[str]) -> list[str]:
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
            result = subprocess.run(  # noqa: UP022
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
