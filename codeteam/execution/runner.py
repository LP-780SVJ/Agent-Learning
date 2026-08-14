from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from threading import Thread
from typing import BinaryIO

from codeteam.execution.models import (
    CommandLimits,
    CommandRequest,
    CommandResult,
    CommandStatus,
)
from codeteam.execution.output_limiter import OutputLimiter

_DEFAULT_ALLOWED_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
)


class CommandRunner:
    def __init__(
        self,
        limits: CommandLimits | None = None,
        *,
        allowed_env_vars: tuple[str, ...] = _DEFAULT_ALLOWED_ENV,
    ) -> None:
        self._limits = limits or CommandLimits()
        self._allowed_env_vars = allowed_env_vars

    def run(self, request: CommandRequest) -> CommandResult:
        start_time = time.monotonic()

        workspace_root = request.workspace_root.expanduser().resolve(strict=False)
        cwd = request.cwd.expanduser().resolve(strict=False)

        if not _is_inside_workspace(cwd, workspace_root):
            return _start_failed_result(
                request,
                start_time,
                f"cwd is outside workspace: {cwd}",
            )

        stdout_limiter = OutputLimiter(self._limits.max_stdout_bytes)
        stderr_limiter = OutputLimiter(self._limits.max_stderr_bytes)

        try:
            process = subprocess.Popen(
                list(request.argv),
                cwd=cwd,
                env=self._build_env(),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=(os.name == "posix"),
            )
        except OSError as error:
            return _start_failed_result(request, start_time, str(error))

        stdout_thread = Thread(
            target=_drain_stream,
            args=(process.stdout, stdout_limiter),
            daemon=True,
        )
        stderr_thread = Thread(
            target=_drain_stream,
            args=(process.stderr, stderr_limiter),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        terminated_with_sigterm = False
        terminated_with_sigkill = False

        timeout = request.timeout_seconds or self._limits.timeout_seconds

        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminated_with_sigterm = True
            _terminate_process_group(process)

            try:
                exit_code = process.wait(
                    timeout=self._limits.terminate_grace_seconds,
                )
            except subprocess.TimeoutExpired:
                terminated_with_sigkill = True
                _kill_process_group(process)
                exit_code = process.wait()

        stdout_thread.join()
        stderr_thread.join()

        stdout = stdout_limiter.snapshot()
        stderr = stderr_limiter.snapshot()

        if timed_out:
            status = CommandStatus.TIMED_OUT
        elif exit_code == 0:
            status = CommandStatus.SUCCESS
        else:
            status = CommandStatus.NONZERO_EXIT

        return CommandResult(
            status=status,
            argv=request.argv,
            cwd=cwd,
            exit_code=exit_code,
            stdout=stdout.text,
            stderr=stderr.text,
            stdout_total_bytes=stdout.total_bytes,
            stderr_total_bytes=stderr.total_bytes,
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
            timed_out=timed_out,
            duration_ms=(time.monotonic() - start_time) * 1000,
            terminated_with_sigterm=terminated_with_sigterm,
            terminated_with_sigkill=terminated_with_sigkill,
        )

    def _build_env(self) -> dict[str, str]:
        return {
            name: os.environ[name]
            for name in self._allowed_env_vars
            if name in os.environ
        }


def _drain_stream(stream: BinaryIO | None, limiter: OutputLimiter) -> None:
    if stream is None:
        return

    with stream:
        for chunk in iter(lambda: stream.read(8192), b""):
            limiter.feed(chunk)


def _is_inside_workspace(path: Path, workspace_root: Path) -> bool:
    return path == workspace_root or workspace_root in path.parents


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _start_failed_result(
    request: CommandRequest,
    start_time: float,
    error: str,
) -> CommandResult:
    return CommandResult(
        status=CommandStatus.START_FAILED,
        argv=request.argv,
        cwd=request.cwd,
        error=error,
        duration_ms=(time.monotonic() - start_time) * 1000,
    )
