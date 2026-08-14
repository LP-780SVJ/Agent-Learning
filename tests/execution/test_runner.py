from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from codeteam.execution.models import (
    CommandLimits,
    CommandRequest,
    CommandStatus,
)
from codeteam.execution.runner import CommandRunner


def _request(
    tmp_path: Path,
    argv: tuple[str, ...],
    *,
    cwd: Path | None = None,
    timeout_seconds: float | None = None,
) -> CommandRequest:
    return CommandRequest(
        argv=argv,
        cwd=tmp_path if cwd is None else cwd,
        workspace_root=tmp_path,
        task_id="task-1",
        agent_id="agent-1",
        timeout_seconds=timeout_seconds,
    )


def _python(script: str) -> tuple[str, ...]:
    return (sys.executable, "-c", script)


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_runner_reports_success(tmp_path: Path) -> None:
    runner = CommandRunner()

    result = runner.run(_request(tmp_path, _python("print('ok')")))

    assert result.status is CommandStatus.SUCCESS
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_runner_reports_nonzero_exit(tmp_path: Path) -> None:
    runner = CommandRunner()

    result = runner.run(_request(tmp_path, _python("import sys; sys.exit(7)")))

    assert result.status is CommandStatus.NONZERO_EXIT
    assert result.exit_code == 7


def test_runner_reports_start_failed(tmp_path: Path) -> None:
    runner = CommandRunner()

    result = runner.run(
        _request(tmp_path, ("definitely-not-a-real-command-xyz",))
    )

    assert result.status is CommandStatus.START_FAILED
    assert result.error


def test_runner_reports_timeout(tmp_path: Path) -> None:
    runner = CommandRunner(CommandLimits(timeout_seconds=0.2))

    result = runner.run(_request(tmp_path, _python("import time; time.sleep(5)")))

    assert result.status is CommandStatus.TIMED_OUT
    assert result.timed_out is True
    assert result.terminated_with_sigterm is True


def test_runner_falls_back_to_sigkill_after_sigterm(tmp_path: Path) -> None:
    runner = CommandRunner(
        CommandLimits(timeout_seconds=0.2, terminate_grace_seconds=0.1)
    )
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )

    result = runner.run(_request(tmp_path, _python(script)))

    assert result.status is CommandStatus.TIMED_OUT
    assert result.terminated_with_sigterm is True
    assert result.terminated_with_sigkill is True


def test_runner_process_group_cleans_child_process(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    runner = CommandRunner(
        CommandLimits(timeout_seconds=0.3, terminate_grace_seconds=0.1)
    )
    child_script = "import time; time.sleep(30)"
    parent_script = (
        "from pathlib import Path\n"
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child_script!r}])\n"
        f"Path({str(child_pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(30)\n"
    )

    result = runner.run(_request(tmp_path, _python(parent_script)))

    assert result.status is CommandStatus.TIMED_OUT
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and _pid_is_alive(child_pid):
        time.sleep(0.05)
    assert _pid_is_alive(child_pid) is False


def test_runner_uses_devnull_for_stdin(tmp_path: Path) -> None:
    runner = CommandRunner(CommandLimits(timeout_seconds=1))
    script = "import sys; print('eof' if sys.stdin.read() == '' else 'data')"

    result = runner.run(_request(tmp_path, _python(script)))

    assert result.status is CommandStatus.SUCCESS
    assert result.stdout.strip() == "eof"


def test_runner_truncates_large_stdout_without_deadlock(tmp_path: Path) -> None:
    runner = CommandRunner(CommandLimits(max_stdout_bytes=128))
    script = "import sys; sys.stdout.write('x' * 1000000); sys.stdout.flush()"

    result = runner.run(_request(tmp_path, _python(script)))

    assert result.status is CommandStatus.SUCCESS
    assert result.stdout_total_bytes == 1000000
    assert result.stdout_truncated is True
    assert len(result.stdout.encode()) <= 128


def test_runner_truncates_large_stderr_without_deadlock(tmp_path: Path) -> None:
    runner = CommandRunner(CommandLimits(max_stderr_bytes=128))
    script = "import sys; sys.stderr.write('e' * 1000000); sys.stderr.flush()"

    result = runner.run(_request(tmp_path, _python(script)))

    assert result.status is CommandStatus.SUCCESS
    assert result.stderr_total_bytes == 1000000
    assert result.stderr_truncated is True
    assert len(result.stderr.encode()) <= 128


def test_runner_drains_concurrent_stdout_and_stderr(tmp_path: Path) -> None:
    runner = CommandRunner(
        CommandLimits(max_stdout_bytes=128, max_stderr_bytes=128)
    )
    script = (
        "import sys\n"
        "sys.stdout.write('o' * 500000)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('e' * 500000)\n"
        "sys.stderr.flush()\n"
    )

    result = runner.run(_request(tmp_path, _python(script)))

    assert result.status is CommandStatus.SUCCESS
    assert result.stdout_total_bytes == 500000
    assert result.stderr_total_bytes == 500000
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_runner_env_allowlist_does_not_leak_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "secret-value")
    monkeypatch.setenv("API_KEY", "api-key-value")
    monkeypatch.setenv("TOKEN", "token-value")
    runner = CommandRunner()
    script = (
        "import os\n"
        "names = ['SECRET_TOKEN', 'API_KEY', 'TOKEN']\n"
        "print(','.join(name for name in names if name in os.environ))\n"
    )

    result = runner.run(_request(tmp_path, _python(script)))

    assert result.status is CommandStatus.SUCCESS
    assert result.stdout.strip() == ""


def test_runner_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    runner = CommandRunner()
    outside = tmp_path.parent

    result = runner.run(_request(tmp_path, _python("print('no')"), cwd=outside))

    assert result.status is CommandStatus.START_FAILED
    assert "outside workspace" in (result.error or "")
