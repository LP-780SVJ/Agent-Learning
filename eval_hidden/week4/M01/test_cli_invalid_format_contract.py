import os
import subprocess
import sys
from pathlib import Path


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        shell=False,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )


def test_diff_invalid_format_exits_2_without_traceback(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "Hidden Eval")
    _run_git(repo, "config", "user.email", "hidden@example.com")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    _run_git(repo, "add", "app.py")
    _run_git(repo, "commit", "-m", "init")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "codeteam.cli.app",
            "diff",
            "ses_missing",
            "--repo",
            str(repo),
            "--format",
            "xml",
        ],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        shell=False,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
