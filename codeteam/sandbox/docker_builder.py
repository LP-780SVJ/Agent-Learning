from __future__ import annotations

from pathlib import Path

from codeteam.sandbox.errors import SandboxMountError
from codeteam.sandbox.models import SandboxExecutionContext

# ---- 危险路径常量 -------------------------------------------
EXACT_FORBIDDEN_HOST_ROOTS = frozenset({
    "/",
    "/private/var",
    "/var",
})

RECURSIVE_FORBIDDEN_HOST_PATHS = frozenset({
    "/etc",
    "/private/var/backups",
    "/private/var/db",
    "/private/var/lib",
    "/private/var/log",
    "/private/var/root",
    "/usr",
    "/var/backups",
    "/var/db",
    "/var/lib",
    "/var/log",
    "/var/root",
    "/var/run/docker.sock",
})

FORBIDDEN_PATH_MARKERS = frozenset({
    ".ssh",
    ".aws",
    ".kube",
    ".docker",
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
})
# ------------------------------------------------------------

class DockerCommandBuilder:
    """把 SandboxExecutionContext 转换成 docker run argv。"""

    def build(self, context: SandboxExecutionContext) -> tuple[str, ...]:
        profile = context.profile

        argv: list[str] = [
            "docker",
            "run",
            "--rm",
            f"--pull={profile.pull_policy}",
            "--workdir",
            str(context.container_cwd),
        ]

        if not profile.network_enabled:
            argv.extend(["--network", "none"])

        if profile.read_only_root:
            argv.append("--read-only")

        if profile.drop_all_capabilities:
            argv.extend(["--cap-drop", "ALL"])

        if profile.no_new_privileges:
            argv.extend(["--security-opt", "no-new-privileges"])

        argv.extend([
            "--memory",
            f"{profile.memory_mb}m",
            "--memory-swap",
            f"{profile.memory_mb}m",
            "--cpus",
            str(profile.cpus),
            "--pids-limit",
            str(profile.pids_limit),
        ])

        argv.extend([
            "--mount",
            _workspace_mount_spec(context),
        ])

        argv.append(profile.image)
        argv.extend(context.argv)

        return tuple(argv)

# ---- HELPER FUNCTIONS ---------------------------------------------
def _workspace_mount_spec(context: SandboxExecutionContext) -> str:
    workspace_root = _docker_mount_source_path(context.workspace_root)
    _validate_workspace_mount_source(workspace_root)

    mount_spec = (
        "type=bind,"
        f"src={workspace_root},"
        f"dst={context.container_workspace}"
    )

    if not context.profile.workspace_write:
        mount_spec = f"{mount_spec},readonly"

    return mount_spec


def _docker_mount_source_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return expanded.absolute()


def _validate_workspace_mount_source(path: Path) -> None:
    if _is_forbidden_host_path(path):
        raise SandboxMountError(f"Forbidden workspace mount source: {path}")

    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & FORBIDDEN_PATH_MARKERS:
        raise SandboxMountError(f"Credential-like workspace mount source: {path}")

    resolved = path.resolve(strict=False)
    if resolved != path:
        _validate_workspace_mount_source(resolved)


def _is_forbidden_host_path(path: Path) -> bool:
    if _is_exact_forbidden_host_root(path):
        return True

    return _is_recursive_forbidden_host_path(path)


def _is_exact_forbidden_host_root(path: Path) -> bool:
    for forbidden_text in EXACT_FORBIDDEN_HOST_ROOTS:
        forbidden = Path(forbidden_text)
        if path == forbidden:
            return True

    return False


def _is_recursive_forbidden_host_path(path: Path) -> bool:
    for forbidden_text in RECURSIVE_FORBIDDEN_HOST_PATHS:
        forbidden = Path(forbidden_text).resolve(strict=False)

        if _is_relative_to(path.resolve(strict=False), forbidden):
            return True

    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
