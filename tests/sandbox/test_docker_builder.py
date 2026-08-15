from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from codeteam.execution.models import CommandRequest, CommandResult, CommandStatus
from codeteam.execution.runner import CommandRunner
from codeteam.sandbox.docker_builder import DockerCommandBuilder
from codeteam.sandbox.docker_runner import DockerRunner
from codeteam.sandbox.errors import SandboxMountError
from codeteam.sandbox.models import SandboxExecutionContext, SandboxProfile


def _context(
    workspace: Path,
    *,
    cwd: Path | None = None,
    profile: SandboxProfile | None = None,
) -> SandboxExecutionContext:
    command_cwd = workspace if cwd is None else cwd
    return SandboxExecutionContext(
        argv=("pytest",),
        workspace_root=workspace,
        cwd=command_cwd,
        profile=SandboxProfile() if profile is None else profile,
    )


def _build_mount_by_destination(argv: tuple[str, ...], destination: str) -> str:
    mounts = [
        argv[index + 1]
        for index, value in enumerate(argv)
        if value == "--mount"
    ]
    for mount in mounts:
        if f"dst={destination}" in mount:
            return mount
    raise AssertionError(f"missing mount for destination {destination}")


class RecordingRunner:
    def __init__(self) -> None:
        self.requests: list[CommandRequest] = []

    def run(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        return CommandResult(
            status=CommandStatus.SUCCESS,
            argv=request.argv,
            cwd=request.cwd,
            exit_code=0,
        )


def test_default_profile_builds_hardened_docker_run_argv(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    argv = DockerCommandBuilder().build(_context(workspace))
    mount = _build_mount_by_destination(argv, "/workspace")

    assert argv[:3] == ("docker", "run", "--rm")
    assert "--pull=never" in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert argv[argv.index("--memory") + 1] == "512m"
    assert argv[argv.index("--memory-swap") + 1] == "512m"
    assert argv[argv.index("--cpus") + 1] == "1.0"
    assert argv[argv.index("--pids-limit") + 1] == "256"
    assert mount == f"type=bind,src={workspace.resolve()},dst=/workspace"
    assert "readonly" not in mount
    assert argv[-2:] == ("codeteam-sandbox:latest", "pytest")


def test_builder_returns_argv_tuple_not_shell_string(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    argv = DockerCommandBuilder().build(_context(workspace))

    assert isinstance(argv, tuple)
    assert not isinstance(argv, str)
    assert all(isinstance(part, str) for part in argv)


def test_workspace_write_false_makes_workspace_mount_read_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profile = SandboxProfile(workspace_write=False)

    argv = DockerCommandBuilder().build(_context(workspace, profile=profile))
    mount = _build_mount_by_destination(argv, "/workspace")

    assert mount == f"type=bind,src={workspace.resolve()},dst=/workspace,readonly"


def test_workspace_mount_preserves_docker_visible_tmp_alias() -> None:
    workspace = Path("/tmp/codeteam-sandbox-alias")

    argv = DockerCommandBuilder().build(_context(workspace))
    mount = _build_mount_by_destination(argv, "/workspace")

    assert mount == "type=bind,src=/tmp/codeteam-sandbox-alias,dst=/workspace"


def test_workspace_mount_allows_tmp_path_under_private_var_folders() -> None:
    workspace = Path("/private/var/folders/codeteam-pytest/workspace")

    argv = DockerCommandBuilder().build(_context(workspace))
    mount = _build_mount_by_destination(argv, "/workspace")

    assert mount == (
        "type=bind,"
        "src=/private/var/folders/codeteam-pytest/workspace,"
        "dst=/workspace"
    )


def test_workspace_mount_allows_var_folders_alias() -> None:
    workspace = Path("/var/folders/codeteam-pytest/workspace")

    argv = DockerCommandBuilder().build(_context(workspace))
    mount = _build_mount_by_destination(argv, "/workspace")

    assert mount == (
        "type=bind,"
        "src=/var/folders/codeteam-pytest/workspace,"
        "dst=/workspace"
    )


def test_workspace_mount_allows_pytest_tmp_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    argv = DockerCommandBuilder().build(_context(workspace))
    mount = _build_mount_by_destination(argv, "/workspace")

    assert mount == f"type=bind,src={workspace},dst=/workspace"


def test_network_enabled_omits_network_none_but_keeps_hardening(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profile = SandboxProfile(network_enabled=True)

    argv = DockerCommandBuilder().build(_context(workspace, profile=profile))

    assert "--network" not in argv
    assert "none" not in argv
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    assert "--pull=never" in argv


@pytest.mark.parametrize(
    "dangerous_workspace",
    [
        Path("/"),
        Path("/etc"),
        Path("/var"),
        Path("/private/var"),
        Path("/usr"),
        Path("/var/run/docker.sock"),
    ],
)
def test_workspace_mount_source_rejects_forbidden_host_paths(
    dangerous_workspace: Path,
) -> None:
    context = SandboxExecutionContext(
        argv=("pytest",),
        workspace_root=dangerous_workspace,
        cwd=dangerous_workspace,
    )

    with pytest.raises(SandboxMountError):
        DockerCommandBuilder().build(context)


@pytest.mark.parametrize(
    "dangerous_workspace",
    [
        Path("/etc/project"),
        Path("/usr/local/project"),
        Path("/var/backups/project"),
        Path("/var/db/project"),
        Path("/var/lib/project"),
        Path("/var/log/project"),
        Path("/var/root/project"),
        Path("/private/var/db/project"),
        Path("/private/var/lib/project"),
        Path("/private/var/root/project"),
    ],
)
def test_workspace_mount_source_rejects_sensitive_host_subtrees(
    dangerous_workspace: Path,
) -> None:
    context = SandboxExecutionContext(
        argv=("pytest",),
        workspace_root=dangerous_workspace,
        cwd=dangerous_workspace,
    )

    with pytest.raises(SandboxMountError):
        DockerCommandBuilder().build(context)


@pytest.mark.parametrize(
    "marker",
    [".ssh", ".env", ".aws", ".kube", ".docker", ".npmrc", ".pypirc", ".netrc"],
)
def test_workspace_mount_source_rejects_credential_markers(
    tmp_path: Path,
    marker: str,
) -> None:
    workspace = tmp_path / marker / "workspace"
    workspace.mkdir(parents=True)

    with pytest.raises(SandboxMountError):
        DockerCommandBuilder().build(_context(workspace))


def test_context_rejects_cwd_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValidationError):
        SandboxExecutionContext(
            argv=("pytest",),
            workspace_root=workspace,
            cwd=outside,
        )


def test_container_cwd_maps_host_cwd_under_container_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    tests_dir = workspace / "tests" / "unit"
    tests_dir.mkdir(parents=True)

    context = SandboxExecutionContext(
        argv=("pytest",),
        workspace_root=workspace,
        cwd=tests_dir,
    )

    assert context.container_cwd == Path("/workspace/tests/unit")


def test_builder_outputs_exactly_one_workspace_bind_mount(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    argv = DockerCommandBuilder().build(_context(workspace))
    mounts = [
        argv[index + 1]
        for index, value in enumerate(argv)
        if value == "--mount"
    ]

    assert mounts == [f"type=bind,src={workspace.resolve()},dst=/workspace"]
    assert "--privileged" not in argv
    assert "--device" not in argv
    assert "--cap-add" not in argv
    assert "/var/run/docker.sock" not in " ".join(argv)


def test_docker_runner_delegates_structured_docker_argv_to_command_runner(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    context = SandboxExecutionContext(
        argv=("python", "--version"),
        workspace_root=workspace,
        cwd=workspace,
    )
    recording_runner = RecordingRunner()

    result = DockerRunner(
        runner=cast(CommandRunner, recording_runner),
    ).run(context)

    assert result.status is CommandStatus.SUCCESS
    assert len(recording_runner.requests) == 1
    request = recording_runner.requests[0]
    assert isinstance(request.argv, tuple)
    assert request.argv == DockerCommandBuilder().build(context)
    assert request.argv[:2] == ("docker", "run")
    assert request.cwd == workspace
    assert request.workspace_root == workspace
