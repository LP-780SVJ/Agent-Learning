from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
from pathlib import Path

from codeteam.session.models import SessionStatus
from codeteam.session.store import JsonSessionStore


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


def _run_cli_with_env(
    *args: str,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codeteam.cli.app", *args],
        cwd=cwd,
        env={**os.environ, **env},
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


def _git_common_dir(repo: Path) -> Path:
    return (repo / _run_git(repo, "rev-parse", "--git-common-dir")).resolve()


def _session_store(repo: Path) -> JsonSessionStore:
    return JsonSessionStore(_git_common_dir(repo) / "codeteam" / "sessions")


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


def _read_line_with_timeout(
    proc: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> str:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        events = selector.select(timeout_seconds)
        if not events:
            raise AssertionError("timed out waiting for CLI output")
        return proc.stdout.readline()
    finally:
        selector.close()


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


def test_real_process_diff_invalid_format_exits_2_without_traceback(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    result = _run_cli(
        "diff",
        "ses_missing",
        "--repo",
        str(repo),
        "--format",
        "xml",
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Invalid value" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (_session_store(repo).session_dir("ses_missing") / "session.json").exists()


def test_real_process_rollback_invalid_format_exits_2_without_traceback(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)

    result = _run_cli(
        "rollback",
        "ses_missing",
        "cp-000001",
        "--repo",
        str(repo),
        "--format",
        "xml",
        cwd=tmp_path,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Invalid value" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (_session_store(repo).session_dir("ses_missing") / "session.json").exists()


def test_run_sigint_pauses_session_and_resume_uses_new_process(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "codeteam.cli.app", "run", "pause me", "--repo", str(repo)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "CODETEAM_CLI_TEST_WAIT_AFTER_SESSION": "1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        session_line = _read_line_with_timeout(proc, timeout_seconds=10)
        assert session_line.startswith("Session: ")
        session_id = session_line.split("Session: ", 1)[1].strip()
        proc.send_signal(signal.SIGINT)
        stdout_tail, stderr = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)

    stdout = session_line + stdout_tail
    assert proc.returncode == 130
    assert "Status: paused" in stdout
    assert "Traceback" not in stdout
    assert "Traceback" not in stderr

    paused = _session_store(repo).load(session_id)
    assert paused.status is SessionStatus.PAUSED

    resumed = _run_cli_with_env(
        "resume",
        session_id,
        "--repo",
        str(repo),
        cwd=tmp_path,
        env={"PYTHONUNBUFFERED": "1"},
    )

    assert resumed.returncode == 0
    assert f"Session: {session_id}" in resumed.stdout
    assert "Status: running" in resumed.stdout
    assert "Traceback" not in resumed.stdout
    assert "Traceback" not in resumed.stderr
