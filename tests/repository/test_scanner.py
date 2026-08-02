import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from codeteam.repository.models import FileKind
from codeteam.repository.scanner import RepositoryScanner


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _files_by_path(snapshot: object) -> dict[str, object]:
    return {file.path: file for file in snapshot.files}


def _status_value(record: object) -> str:
    status = getattr(record, "status", None)
    if status is None:
        status = getattr(record, "git_status", None)
    if status is None:
        status = getattr(record, "state", None)
    if status is None:
        raise AssertionError(f"Repository file has no Git tracked state: {record!r}")
    return str(getattr(status, "value", status))


def _importance_value(record: object) -> str:
    importance = getattr(record, "importance", None)
    if importance is None:
        raise AssertionError(f"Repository file has no importance field: {record!r}")
    return str(getattr(importance, "value", importance))


class RepositoryScannerTests(unittest.TestCase):
    def test_git_scan_marks_tracked_untracked_and_ignored_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
            (repo / "tracked.py").write_text("print('tracked')\n", encoding="utf-8")
            (repo / "untracked.py").write_text("print('untracked')\n", encoding="utf-8")
            (repo / "ignored.log").write_text("ignored\n", encoding="utf-8")
            _run_git(repo, "add", "tracked.py")

            snapshot = RepositoryScanner(repo).scan()
            by_path = _files_by_path(snapshot)

            self.assertTrue(snapshot.is_git_repo)
            self.assertEqual(_status_value(by_path["tracked.py"]), "tracked")
            self.assertEqual(_status_value(by_path["untracked.py"]), "untracked")
            self.assertNotIn("ignored.log", by_path)

    def test_git_scan_keeps_tracked_file_after_ignore_rule_is_added(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            (repo / "already.log").write_text("tracked\n", encoding="utf-8")
            _run_git(repo, "add", "already.log")
            (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")

            by_path = _files_by_path(RepositoryScanner(repo).scan())

            self.assertEqual(_status_value(by_path["already.log"]), "tracked")

    @unittest.skipIf(os.name == "nt", "Newline file names are not portable on Windows.")
    def test_git_scan_preserves_space_unicode_and_newline_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            expected_paths = {
                "name with spaces.py",
                "中文文件.py",
                "line\nbreak.py",
            }
            for relative_path in expected_paths:
                (repo / relative_path).write_text("print('ok')\n", encoding="utf-8")
            _run_git(repo, "add", *sorted(expected_paths))

            by_path = _files_by_path(RepositoryScanner(repo).scan())

            self.assertEqual(set(by_path), expected_paths)

    def test_git_scan_marks_deleted_tracked_file_without_stat_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _run_git(repo, "init")
            deleted_path = repo / "deleted.py"
            deleted_path.write_text("print('gone')\n", encoding="utf-8")
            _run_git(repo, "add", "deleted.py")
            deleted_path.unlink()

            by_path = _files_by_path(RepositoryScanner(repo).scan())

            self.assertEqual(_status_value(by_path["deleted.py"]), "deleted")

    def test_scan_marks_binary_generated_tests_and_high_importance_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "generated").mkdir()
            (root / "generated" / "client.py").write_text("# generated\n", encoding="utf-8")
            (root / "test_app.py").write_text("def test_app(): pass\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# instructions\n", encoding="utf-8")
            (root / "payload.bin").write_bytes(b"\x00\x01\x02")

            by_path = _files_by_path(RepositoryScanner(root).scan())

            self.assertEqual(by_path["generated/client.py"].kind, FileKind.GENERATED)
            self.assertEqual(by_path["test_app.py"].kind, FileKind.TEST)
            self.assertEqual(by_path["AGENTS.md"].kind, FileKind.INSTRUCTION)
            self.assertEqual(_importance_value(by_path["AGENTS.md"]), "high")
            self.assertEqual(by_path["payload.bin"].kind, FileKind.BINARY)

    def test_non_git_directory_falls_back_to_filesystem_scan_and_filters_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "node_modules" / "package").mkdir(parents=True)
            (root / "node_modules" / "package" / "index.js").write_text(
                "module.exports = {}\n",
                encoding="utf-8",
            )
            outside = Path(temp_dir).parent / "outside-scanner-target.txt"
            outside.write_text("outside\n", encoding="utf-8")
            try:
                os.symlink(outside, root / "outside-link.txt")
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")

            snapshot = RepositoryScanner(root).scan()
            paths = {file.path for file in snapshot.files}

            self.assertFalse(snapshot.is_git_repo)
            self.assertIn("src/app.py", paths)
            self.assertNotIn("node_modules/package/index.js", paths)
            self.assertNotIn("outside-link.txt", paths)
