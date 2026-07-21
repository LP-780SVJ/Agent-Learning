import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from codeteam.tools.base import RegisteredTool


DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_BYTES = 8_192
DEFAULT_ALLOWED_ENV_VARS = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "LANG",
        "LC_ALL",
        "TERM",
        "PYTHONUNBUFFERED",
    }
)
DANGEROUS_COMMANDS = {
    "sudo",
    "su",
    "doas",
    "rm",
    "rmdir",
    "chmod",
    "chown",
    "chgrp",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "kill",
    "killall",
    "pkill",
}


@dataclass
class ShellToolConfig:
    workspace_root: Path | str
    default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_timeout_seconds: float = MAX_TIMEOUT_SECONDS
    max_output_bytes: int = MAX_OUTPUT_BYTES
    allowed_env_vars: frozenset[str] = DEFAULT_ALLOWED_ENV_VARS

    def __post_init__(self) -> None:
        workspace_root = Path(self.workspace_root).resolve()
        if not workspace_root.exists() or not workspace_root.is_dir():
            raise ValueError(
                f"Workspace root must be an existing directory: {workspace_root}"
            )
        if self.default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive.")
        if self.max_timeout_seconds <= 0:
            raise ValueError("max_timeout_seconds must be positive.")
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default_timeout_seconds cannot exceed max_timeout_seconds.")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive.")

        self.workspace_root = workspace_root
        self.allowed_env_vars = frozenset(self.allowed_env_vars)


class RunCommandArgs(BaseModel):
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_seconds: float | None = Field(default=None, gt=0)
    env: dict[str, str] = Field(default_factory=dict)
    max_output_bytes: int | None = Field(default=None, gt=0)


class ShellCommandResult(BaseModel):
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_seconds: float


def run_command(args: RunCommandArgs, config: ShellToolConfig) -> str:
    cwd = _resolve_cwd(args.cwd, config)
    _validate_argv(args.argv, cwd, config)
    timeout_seconds = _resolve_timeout(args.timeout_seconds, config)
    max_output_bytes = _resolve_max_output_bytes(args.max_output_bytes, config)
    env = _build_env(args.env, config)

    result = _run_process(
        argv=args.argv,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )

    return result.model_dump_json()


def create_shell_tool(
    workspace_root: Path | str,
    default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_timeout_seconds: float = MAX_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    allowed_env_vars: frozenset[str] = DEFAULT_ALLOWED_ENV_VARS,
) -> RegisteredTool:
    config = ShellToolConfig(
        workspace_root=workspace_root,
        default_timeout_seconds=default_timeout_seconds,
        max_timeout_seconds=max_timeout_seconds,
        max_output_bytes=max_output_bytes,
        allowed_env_vars=allowed_env_vars,
    )

    return RegisteredTool(
        name="run_command",
        description="Run a safe command inside the workspace.",
        args_schema=RunCommandArgs,
        func=lambda args: run_command(args, config),
    )


def _resolve_cwd(cwd: str, config: ShellToolConfig) -> Path:
    requested_cwd = Path(cwd)
    if requested_cwd.is_absolute():
        raise ValueError("cwd must be relative to the workspace.")

    candidate = (config.workspace_root / requested_cwd).resolve(strict=False)
    if not _is_relative_to(candidate, config.workspace_root):
        raise ValueError(f"cwd escapes workspace: {cwd}")
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError(f"cwd must be an existing directory: {cwd}")

    return candidate


def _validate_argv(argv: list[str], cwd: Path, config: ShellToolConfig) -> None:
    if not argv:
        raise ValueError("argv must not be empty.")
    if any(argument == "" for argument in argv):
        raise ValueError("argv must not contain empty strings.")

    command_name = Path(argv[0]).name
    if command_name in DANGEROUS_COMMANDS:
        raise ValueError(f"Dangerous command is not allowed: {command_name}")
    if command_name == "git" and "push" in argv[1:]:
        raise ValueError("Dangerous command is not allowed: git push")

    for argument in argv[1:]:
        if _looks_like_path_argument(argument, cwd):
            _ensure_path_argument_inside_workspace(argument, cwd, config)


def _build_env(requested_env: dict[str, str], config: ShellToolConfig) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name in config.allowed_env_vars
    }

    for name, value in requested_env.items():
        if name not in config.allowed_env_vars:
            raise ValueError(f"Environment variable is not allowed: {name}")
        env[name] = value

    return env


def _truncate_text(text: str, max_output_bytes: int) -> tuple[str, bool]:
    encoded_text = text.encode("utf-8")
    if len(encoded_text) <= max_output_bytes:
        return text, False

    truncated_text = encoded_text[:max_output_bytes].decode(
        "utf-8",
        errors="ignore",
    )
    return truncated_text, True


def _run_process(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
) -> ShellCommandResult:
    start_time = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    timed_out = False
    exit_code: int | None
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
        exit_code = None

    duration_seconds = time.monotonic() - start_time
    stdout, stdout_truncated = _truncate_text(stdout, max_output_bytes)
    stderr, stderr_truncated = _truncate_text(stderr, max_output_bytes)

    return ShellCommandResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        duration_seconds=round(duration_seconds, 6),
    )


def _resolve_timeout(
    timeout_seconds: float | None,
    config: ShellToolConfig,
) -> float:
    timeout = (
        config.default_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds
    )
    if timeout > config.max_timeout_seconds:
        raise ValueError(
            f"timeout_seconds cannot exceed {config.max_timeout_seconds} seconds."
        )
    return timeout


def _resolve_max_output_bytes(
    max_output_bytes: int | None,
    config: ShellToolConfig,
) -> int:
    output_bytes = (
        config.max_output_bytes
        if max_output_bytes is None
        else max_output_bytes
    )
    if output_bytes > config.max_output_bytes:
        raise ValueError(
            f"max_output_bytes cannot exceed {config.max_output_bytes} bytes."
        )
    return output_bytes


def _looks_like_path_argument(argument: str, cwd: Path) -> bool:
    if argument.startswith("-"):
        return False
    path = Path(argument)
    return (
        path.is_absolute()
        or argument in {".", ".."}
        or "/" in argument
        or "\\" in argument
        or (cwd / path).exists()
    )


def _ensure_path_argument_inside_workspace(
    argument: str,
    cwd: Path,
    config: ShellToolConfig,
) -> None:
    path = Path(argument)
    candidate = (
        path.resolve(strict=False)
        if path.is_absolute()
        else (cwd / path).resolve(strict=False)
    )
    if not _is_relative_to(candidate, config.workspace_root):
        raise ValueError(f"Path argument escapes workspace: {argument}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
