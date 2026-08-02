import importlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _record_path(record: object) -> str:
    path = getattr(record, "path", None)
    if path is None:
        path = getattr(record, "relative_path", None)
    if path is None:
        raise AssertionError(f"Inventory record has no path field: {record!r}")
    return str(path)


def _record_status(record: object) -> str:
    status = getattr(record, "status", None)
    if status is None:
        status = getattr(record, "git_status", None)
    if status is None:
        status = getattr(record, "state", None)
    if status is None:
        raise AssertionError(f"Inventory record has no tracked state field: {record!r}")
    return str(getattr(status, "value", status))


class GitInventoryTests(unittest.TestCase):
    def _load_inventory_class(self) -> type:
        try:
            module = importlib.import_module("codeteam.repository.git_inventory")
        except ModuleNotFoundError as error:
            self.fail(f"Expected codeteam.repository.git_inventory module: {error}")

        for class_name in ("GitInventory", "GitRepositoryInventory"):
            inventory_class = getattr(module, class_name, None)
            if inventory_class is not None:
                return inventory_class

        self.fail("git_inventory must expose GitInventory or GitRepositoryInventory.")

    def _collect_records(self, repo: Path) -> list[object]:
        inventory = self._load_inventory_class()(repo)
        for method_name in ("scan", "collect", "list_files"):
            method = getattr(inventory, method_name, None)
            if method is not None:
                result = method()
                break
        else:
            self.fail("Git inventory must provide scan(), collect(), or list_files().")

        if hasattr(result, "files"):
            result = result.files
        return list(result)

    def _collect_by_path(self, repo: Path) -> dict[str, object]:
        return {_record_path(record): record for record in self._collect_records(repo)}

    def test_marks_tracked_and_untracked_files_separately_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            _run_git(repo, "add", "tracked.txt")

            by_path = self._collect_by_path(repo)

            self.assertEqual(_record_status(by_path["tracked.txt"]), "tracked")
            self.assertEqual(_record_status(by_path["untracked.txt"]), "untracked")

    def test_ignored_untracked_file_is_hidden_but_tracked_file_stays_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            (repo / "kept.log").write_text("tracked despite ignore\n", encoding="utf-8")
            _run_git(repo, "add", "kept.log")
            (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
            (repo / "ignored.log").write_text("ignored\n", encoding="utf-8")

            by_path = self._collect_by_path(repo)

            self.assertEqual(_record_status(by_path["kept.log"]), "tracked")
            self.assertNotIn("ignored.log", by_path)

    @unittest.skipIf(os.name == "nt", "Newline file names are not portable on Windows.")
    def test_uses_nul_separated_git_output_for_spaces_unicode_and_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            paths = [
                "name with spaces.txt",
                "中文文件.txt",
                "line\nbreak.txt",
            ]
            for relative_path in paths:
                (repo / relative_path).write_text("content\n", encoding="utf-8")
            _run_git(repo, "add", *paths)

            by_path = self._collect_by_path(repo)

            self.assertEqual(sorted(by_path), sorted(paths))

    def test_marks_tracked_file_deleted_when_removed_from_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            deleted_path = repo / "deleted.txt"
            deleted_path.write_text("gone\n", encoding="utf-8")
            _run_git(repo, "add", "deleted.txt")
            deleted_path.unlink()

            by_path = self._collect_by_path(repo)

            self.assertEqual(_record_status(by_path["deleted.txt"]), "deleted")
