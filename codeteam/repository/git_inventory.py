"""Git-backed repository file inventory."""
from __future__ import annotations

import subprocess
from pathlib import Path

from codeteam.repository.models import GitStatus


class GitInventoryRecord:
    def __init__(self, path: str, status: GitStatus) -> None:
        self.path = path
        self.status = status


class GitInventory:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def scan(self) -> list[GitInventoryRecord]:
        tracked = set(self._git_paths(["git", "ls-files", "-z"]))
        deleted = set(self._git_paths(["git", "ls-files", "--deleted", "-z"]))
        untracked = set(
            self._git_paths(["git", "ls-files", "--others", "--exclude-standard", "-z"])
        )

        records: list[GitInventoryRecord] = []
        for path in sorted((tracked - deleted) | deleted | untracked):
            if path in deleted:
                status = GitStatus.DELETED
            elif path in tracked:
                status = GitStatus.TRACKED
            else:
                status = GitStatus.UNTRACKED
            records.append(GitInventoryRecord(path, status))
        return records

    collect = scan
    list_files = scan

    def _git_paths(self, argv: list[str]) -> list[str]:
        result = subprocess.run(
            argv,
            cwd=self.root,
            capture_output=True,
            text=False,
        )
        if result.returncode != 0:
            error_message = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Git command failed: {error_message}")

        paths: list[str] = []
        for raw_path in result.stdout.split(b"\0"):
            if raw_path:
                paths.append(raw_path.decode("utf-8", errors="replace"))
        return paths
