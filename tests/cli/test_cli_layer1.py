from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from codeteam.cli.app import app
from codeteam.cli.requests import (
    DiffRequest,
    ResumeRequest,
    RollbackRequest,
    RunRequest,
)

runner = CliRunner()


def test_help_lists_product_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "resume" in result.stdout
    assert "diff" in result.stdout
    assert "rollback" in result.stdout


def test_run_argv_builds_run_request(monkeypatch) -> None:
    captured: dict[str, RunRequest] = {}

    def fake_run(request: RunRequest) -> None:
        captured["request"] = request
        raise typer.Exit(0)

    monkeypatch.setattr("codeteam.cli.run_command.run_agent_task", fake_run)

    result = runner.invoke(app, ["run", "fix login", "--repo", "."])

    assert result.exit_code == 0
    assert captured["request"].task == "fix login"
    assert captured["request"].repo == Path(".")


def test_resume_argv_builds_resume_request(monkeypatch) -> None:
    captured: dict[str, ResumeRequest] = {}

    def fake_resume(request: ResumeRequest) -> None:
        captured["request"] = request
        raise typer.Exit(0)

    monkeypatch.setattr(
        "codeteam.cli.run_command.resume_agent_session",
        fake_resume,
    )

    result = runner.invoke(
        app,
        [
            "resume",
            "ses_abc",
            "--repo",
            ".",
            "--provider",
            "mock",
            "--model",
            "mock-model",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].session_id == "ses_abc"
    assert captured["request"].provider_id == "mock"
    assert captured["request"].model_id == "mock-model"


def test_diff_argv_builds_diff_request(monkeypatch) -> None:
    captured: dict[str, DiffRequest] = {}

    def fake_diff(request: DiffRequest) -> None:
        captured["request"] = request
        raise typer.Exit(0)

    monkeypatch.setattr("codeteam.cli.run_command.diff_agent_session", fake_diff)

    result = runner.invoke(
        app,
        ["diff", "ses_abc", "--repo", ".", "--base", "main", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["request"].session_id == "ses_abc"
    assert captured["request"].base_ref == "main"
    assert captured["request"].output_format == "json"


def test_rollback_argv_builds_rollback_request(monkeypatch) -> None:
    captured: dict[str, RollbackRequest] = {}

    def fake_rollback(request: RollbackRequest) -> None:
        captured["request"] = request
        raise typer.Exit(0)

    monkeypatch.setattr(
        "codeteam.cli.run_command.rollback_agent_session",
        fake_rollback,
    )

    result = runner.invoke(
        app,
        ["rollback", "ses_abc", "cp-000000", "--repo", ".", "--format", "json"],
    )

    assert result.exit_code == 0
    assert captured["request"].session_id == "ses_abc"
    assert captured["request"].checkpoint_id == "cp-000000"
    assert captured["request"].output_format == "json"


def test_invalid_args_exit_nonzero_without_traceback() -> None:
    result = runner.invoke(app, ["rollback", "ses_only"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_errors_go_to_stderr_not_stdout() -> None:
    result = runner.invoke(app, ["diff", "ses_missing", "--repo", "."])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "session 不存在" in result.stderr
    assert "Traceback" not in result.stderr


def test_diff_invalid_format_exits_2_without_calling_business(
    monkeypatch,
) -> None:
    called = False

    def fake_diff(request: DiffRequest) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("codeteam.cli.run_command.diff_agent_session", fake_diff)

    result = runner.invoke(app, ["diff", "ses_abc", "--format", "xml"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Invalid value" in result.stderr
    assert "Traceback" not in result.stderr
    assert not called


def test_rollback_invalid_format_exits_2_without_calling_business(
    monkeypatch,
) -> None:
    called = False

    def fake_rollback(request: RollbackRequest) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "codeteam.cli.run_command.rollback_agent_session",
        fake_rollback,
    )

    result = runner.invoke(
        app,
        ["rollback", "ses_abc", "cp-000001", "--format", "xml"],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Invalid value" in result.stderr
    assert "Traceback" not in result.stderr
    assert not called
