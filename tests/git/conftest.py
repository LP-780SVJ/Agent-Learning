from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest


GIT_TIMEOUT_SECONDS = 10.0
FileContent = str | bytes
GitRepoFactory = Callable[[Mapping[str, FileContent]], Path]


def run_git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed with {result.returncode}: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )
    return result


def write_file(root: Path, relative_path: str, content: FileContent) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def make_patch(root: Path) -> str:
    result = run_git(
        root,
        "diff",
        "--binary",
        "--find-renames=50%",
        "HEAD",
        "--",
    )
    return result.stdout.decode("utf-8", errors="strict")


def sha256_paths(
    root: Path,
    relative_paths: Sequence[str],
) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.exists() or not path.is_file():
            hashes[relative_path] = None
            continue
        hashes[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def repository_state(
    root: Path,
    relative_paths: Sequence[str],
) -> tuple[dict[str, str | None], bytes]:
    status = run_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
    ).stdout
    return sha256_paths(root, relative_paths), status


@pytest.fixture
def git_repo_factory(tmp_path: Path) -> GitRepoFactory:
    counter = 0

    def create(files: Mapping[str, FileContent]) -> Path:
        nonlocal counter
        counter += 1
        root = tmp_path / f"repo-{counter}" / "worktree"
        root.mkdir(parents=True)

        run_git(root, "init", "--quiet")
        run_git(root, "config", "--local", "user.name", "Test User")
        run_git(
            root,
            "config",
            "--local",
            "user.email",
            "test@example.com",
        )
        run_git(root, "config", "--local", "core.quotepath", "false")

        for relative_path, content in files.items():
            write_file(root, relative_path, content)

        run_git(root, "add", "--all")
        run_git(root, "commit", "--quiet", "--allow-empty", "-m", "baseline")
        return root

    return create
