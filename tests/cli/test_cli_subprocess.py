from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codeteam.cli.app", *args],
        cwd=cwd,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "CodeTeam Test")
    _run_git(repo, "config", "user.email", "codeteam@example.com")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    _run_git(repo, "add", "app.py")
    _run_git(repo, "commit", "-m", "init")
    return repo


def test_python_module_help_runs_in_real_process(tmp_path: Path) -> None:
    result = _run_cli("--help", cwd=tmp_path)

    assert result.returncode == 0
    assert "run" in result.stdout
    assert "resume" in result.stdout
    assert result.stderr == ""


def test_real_process_missing_session_uses_stderr_and_exit_2(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    result = _run_cli("diff", "ses_missing", "--repo", str(repo), cwd=tmp_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "session 不存在" in result.stderr
    assert "Traceback" not in result.stderr


def test_real_process_invalid_args_do_not_expose_traceback(
    tmp_path: Path,
) -> None:
    result = _run_cli("rollback", "ses_only", cwd=tmp_path)

    assert result.returncode != 0
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr

