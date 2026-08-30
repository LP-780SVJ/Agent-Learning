from __future__ import annotations

import posixpath
from typing import Any

CONTAINER_WORKSPACE = "/workspace"
DEFAULT_TEST_TIMEOUT_SECONDS = 120.0


class VerificationCommandError(ValueError):
    """Raised when a visible verification command crosses the workspace boundary."""


def normalize_verification_argv(
    argv: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return the canonical workspace-relative argv used by policy and Docker."""
    if not argv or not all(isinstance(argument, str) for argument in argv):
        raise VerificationCommandError("Verification argv must contain strings.")

    return (
        argv[0],
        *(_normalize_argument(argument) for argument in argv[1:]),
    )


def normalize_verification_cwd(cwd: str) -> str:
    """Normalize a model-visible cwd without exposing host paths to the model."""
    if not isinstance(cwd, str) or not cwd:
        raise VerificationCommandError("Verification cwd must be a non-empty string.")

    normalized = _normalize_workspace_path(cwd)
    if normalized.startswith("/"):
        raise VerificationCommandError(
            "Verification cwd must be workspace-relative; use '.' for the workspace root."
        )
    if normalized == ".." or normalized.startswith("../"):
        raise VerificationCommandError("Verification cwd escapes the workspace.")
    return normalized


def normalize_run_tests_action(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Canonicalize run_tests arguments for semantic repeated-action detection."""
    if tool_name != "run_tests":
        return arguments

    try:
        argv = arguments["argv"]
        if not isinstance(argv, (list, tuple)):
            return arguments
        cwd = arguments.get("cwd", ".")
        timeout = arguments.get("timeout_seconds", DEFAULT_TEST_TIMEOUT_SECONDS)
        return {
            "argv": list(normalize_verification_argv(argv)),
            "cwd": normalize_verification_cwd(cwd),
            "timeout_seconds": float(timeout),
        }
    except (KeyError, TypeError, ValueError):
        return arguments


def normalize_allowed_verification_commands(
    commands: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    return tuple(normalize_verification_argv(command) for command in commands)


def _normalize_argument(argument: str) -> str:
    if argument.startswith("--") and "=" in argument:
        option, value = argument.split("=", 1)
        if value == CONTAINER_WORKSPACE or value.startswith(
            f"{CONTAINER_WORKSPACE}/"
        ):
            return f"{option}={_normalize_workspace_path(value)}"
        if value.startswith("/"):
            raise VerificationCommandError(
                f"Verification option path must be workspace-relative: {argument}"
            )
        if value == ".." or value.startswith("../"):
            raise VerificationCommandError(
                f"Verification option path escapes the workspace: {argument}"
            )
        if value.startswith("./"):
            return f"{option}={posixpath.normpath(value)}"
        return argument

    if argument == CONTAINER_WORKSPACE or argument.startswith(
        (f"{CONTAINER_WORKSPACE}/", "./")
    ):
        return _normalize_workspace_path(argument)
    return argument


def _normalize_workspace_path(value: str) -> str:
    normalized = posixpath.normpath(value)
    if value == CONTAINER_WORKSPACE or value.startswith(
        f"{CONTAINER_WORKSPACE}/"
    ):
        if normalized == CONTAINER_WORKSPACE:
            return "."
        prefix = f"{CONTAINER_WORKSPACE}/"
        if not normalized.startswith(prefix):
            raise VerificationCommandError(
                f"Container path escapes {CONTAINER_WORKSPACE}: {value}"
            )
        return normalized.removeprefix(prefix)
    return normalized
