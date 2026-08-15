from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeteam.execution.models import CommandLimits, CommandStatus
from codeteam.sandbox.docker_runner import DockerRunner
from codeteam.sandbox.models import SandboxExecutionContext, SandboxProfile

SANDBOX_IMAGE = "codeteam-sandbox:latest"
CANARY_SECRET = "codeteam-secret-canary"
SHARED_WORKSPACE_ENV = "CODETEAM_DOCKER_WORKSPACE_PARENT"


@dataclass(frozen=True)
class DockerAvailability:
    available: bool
    reason: str


def _run_docker_probe(argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _docker_availability() -> DockerAvailability:
    try:
        version = _run_docker_probe(("docker", "version"))
    except FileNotFoundError:
        return DockerAvailability(False, "Docker CLI is not installed.")
    except subprocess.TimeoutExpired:
        return DockerAvailability(False, "Docker daemon probe timed out.")

    if version.returncode != 0:
        detail = (version.stderr or version.stdout).strip()
        return DockerAvailability(
            False,
            f"Docker CLI/daemon is unavailable; boundary tests not run: {detail}",
        )

    image = _run_docker_probe(("docker", "image", "inspect", SANDBOX_IMAGE))
    if image.returncode != 0:
        detail = (image.stderr or image.stdout).strip()
        return DockerAvailability(
            False,
            (
                f"Sandbox image {SANDBOX_IMAGE!r} is not present locally; "
                f"tests do not pull images: {detail}"
            ),
        )

    python = _run_docker_probe(
        (
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network",
            "none",
            SANDBOX_IMAGE,
            "python",
            "--version",
        )
    )
    if python.returncode != 0:
        detail = (python.stderr or python.stdout).strip()
        return DockerAvailability(
            False,
            f"Sandbox image lacks a usable python executable: {detail}",
        )

    return DockerAvailability(True, "Docker daemon and sandbox image are available.")


@pytest.fixture(scope="module")
def docker_availability() -> DockerAvailability:
    return _docker_availability()


@pytest.fixture
def docker_workspace(docker_availability: DockerAvailability) -> Iterator[Path]:
    if not docker_availability.available:
        pytest.skip(docker_availability.reason)

    parent = _find_docker_visible_workspace_parent()
    if parent is None:
        pytest.skip(
            "No pytest-writable host path is visible to Docker; "
            f"set {SHARED_WORKSPACE_ENV} to a shared directory."
        )

    workspace = Path(tempfile.mkdtemp(prefix="codeteam-sandbox-", dir=parent))
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _find_docker_visible_workspace_parent() -> Path | None:
    for candidate in _workspace_parent_candidates():
        if _can_share_workspace_parent_with_docker(candidate):
            return candidate
    return None


def _workspace_parent_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []

    configured_parent = os.environ.get(SHARED_WORKSPACE_ENV)
    if configured_parent:
        candidates.append(Path(configured_parent).expanduser())

    candidates.extend(_codex_visualization_candidates())
    candidates.extend([Path.cwd(), Path("/tmp")])

    deduped: dict[Path, None] = {}
    for candidate in candidates:
        deduped.setdefault(candidate, None)
    return tuple(deduped)


def _codex_visualization_candidates() -> tuple[Path, ...]:
    thread_id = os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        return ()

    visualization_root = Path.home() / ".codex" / "visualizations"
    if not visualization_root.exists():
        return ()

    return tuple(visualization_root.glob(f"**/{thread_id}"))


def _can_share_workspace_parent_with_docker(parent: Path) -> bool:
    if not parent.exists() or not parent.is_dir():
        return False

    probe_workspace = Path(
        tempfile.mkdtemp(prefix="codeteam-sandbox-probe-", dir=parent)
    )
    canary = "codeteam-docker-visible-canary"
    try:
        (probe_workspace / "canary.txt").write_text(canary, encoding="utf-8")
        result = _run_docker_probe(
            (
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--mount",
                f"type=bind,src={probe_workspace},dst=/workspace,readonly",
                SANDBOX_IMAGE,
                "python",
                "-c",
                "from pathlib import Path; print(Path('/workspace/canary.txt').read_text())",
            )
        )
        return result.returncode == 0 and canary in result.stdout
    finally:
        shutil.rmtree(probe_workspace, ignore_errors=True)


def _require_docker(availability: DockerAvailability) -> None:
    if not availability.available:
        pytest.skip(availability.reason)


def _run_in_sandbox(
    workspace: Path,
    argv: tuple[str, ...],
    *,
    profile: SandboxProfile | None = None,
):
    context = SandboxExecutionContext(
        argv=argv,
        workspace_root=workspace,
        cwd=workspace,
        profile=SandboxProfile() if profile is None else profile,
    )
    return DockerRunner(limits=CommandLimits(timeout_seconds=10)).run(context)


def _python(code: str) -> tuple[str, ...]:
    return ("python", "-c", code)


def test_read_workspace_succeeds_when_docker_available(
    docker_availability: DockerAvailability,
    docker_workspace: Path,
) -> None:
    _require_docker(docker_availability)
    (docker_workspace / "input.txt").write_text("hello sandbox", encoding="utf-8")

    result = _run_in_sandbox(
        docker_workspace,
        _python("from pathlib import Path; print(Path('/workspace/input.txt').read_text())"),
    )

    assert result.status is CommandStatus.SUCCESS
    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout


def test_write_workspace_succeeds_when_docker_available(
    docker_availability: DockerAvailability,
    docker_workspace: Path,
) -> None:
    _require_docker(docker_availability)

    result = _run_in_sandbox(
        docker_workspace,
        _python(
            "from pathlib import Path; "
            "Path('/workspace/output.txt').write_text('generated')"
        ),
    )

    assert result.status is CommandStatus.SUCCESS
    assert result.exit_code == 0
    assert (docker_workspace / "output.txt").read_text(encoding="utf-8") == "generated"


def test_unmounted_host_secret_is_not_readable_when_docker_available(
    docker_availability: DockerAvailability,
    docker_workspace: Path,
    tmp_path: Path,
) -> None:
    _require_docker(docker_availability)
    secret_path = tmp_path / "host_secret.txt"
    secret_path.write_text(CANARY_SECRET, encoding="utf-8")

    result = _run_in_sandbox(
        docker_workspace,
        _python(
            "from pathlib import Path\n"
            f"path = Path({str(secret_path)!r})\n"
            "try:\n"
            "    print(path.read_text())\n"
            "except Exception as error:\n"
            "    print(type(error).__name__)\n"
            "    raise SystemExit(1)\n"
        ),
    )

    assert result.exit_code != 0
    assert CANARY_SECRET not in result.stdout
    assert CANARY_SECRET not in result.stderr


def test_network_is_blocked_when_docker_available(
    docker_availability: DockerAvailability,
    docker_workspace: Path,
) -> None:
    _require_docker(docker_availability)

    result = _run_in_sandbox(
        docker_workspace,
        _python(
            "import socket\n"
            "sock = socket.socket()\n"
            "sock.settimeout(1)\n"
            "try:\n"
            "    sock.connect(('93.184.216.34', 80))\n"
            "except OSError as error:\n"
            "    print(type(error).__name__)\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        ),
    )

    assert result.status is CommandStatus.SUCCESS
    assert result.exit_code == 0


def test_root_filesystem_write_fails_but_workspace_write_succeeds(
    docker_availability: DockerAvailability,
    docker_workspace: Path,
) -> None:
    _require_docker(docker_availability)

    result = _run_in_sandbox(
        docker_workspace,
        _python(
            "from pathlib import Path\n"
            "Path('/workspace/workspace-write.txt').write_text('ok')\n"
            "try:\n"
            "    Path('/rootfs-test.txt').write_text('bad')\n"
            "except OSError as error:\n"
            "    print(type(error).__name__)\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        ),
    )

    assert result.status is CommandStatus.SUCCESS
    assert result.exit_code == 0
    assert (docker_workspace / "workspace-write.txt").read_text(encoding="utf-8") == "ok"


def test_docker_socket_is_not_mounted_when_docker_available(
    docker_availability: DockerAvailability,
    docker_workspace: Path,
) -> None:
    _require_docker(docker_availability)

    result = _run_in_sandbox(
        docker_workspace,
        _python(
            "from pathlib import Path\n"
            "path = Path('/var/run/docker.sock')\n"
            "print('exists' if path.exists() else 'missing')\n"
            "raise SystemExit(1 if path.exists() else 0)\n"
        ),
    )

    assert result.status is CommandStatus.SUCCESS
    assert result.exit_code == 0
    assert "missing" in result.stdout
    assert "/var/run/docker.sock" not in result.stderr
