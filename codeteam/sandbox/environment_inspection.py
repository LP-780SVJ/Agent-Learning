from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, model_validator

from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.sandbox.docker_runner import DockerRunner
from codeteam.sandbox.models import SandboxExecutionContext, SandboxProfile

MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
EXECUTABLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_FIXED_PROBE = (
    "import importlib.machinery\n"
    "import json\n"
    "import shutil\n"
    "import sys\n"
    "kind, name = sys.argv[1], sys.argv[2]\n"
    "if kind == 'python_module':\n"
    "    value = name in sys.builtin_module_names\n"
    "    if not value:\n"
    "        search_path = None\n"
    "        prefix = []\n"
    "        spec = None\n"
    "        for part in name.split('.'):\n"
    "            prefix.append(part)\n"
    "            spec = importlib.machinery.PathFinder.find_spec(\n"
    "                '.'.join(prefix), search_path\n"
    "            )\n"
    "            if spec is None:\n"
    "                break\n"
    "            search_path = spec.submodule_search_locations\n"
    "        value = spec is not None\n"
    "else:\n"
    "    value = shutil.which(name) is not None\n"
    "print(json.dumps({'runtime_available': value}))\n"
)


class EnvironmentInspectionArgs(BaseModel):
    python_module: str | None = None
    executable: str | None = None

    @model_validator(mode="after")
    def validate_probe(self) -> EnvironmentInspectionArgs:
        if (self.python_module is None) == (self.executable is None):
            raise ValueError("Provide exactly one of python_module or executable.")
        if self.python_module is not None and not MODULE_NAME.fullmatch(
            self.python_module
        ):
            raise ValueError("python_module must be a dotted Python module name.")
        if self.executable is not None and not EXECUTABLE_NAME.fullmatch(
            self.executable
        ):
            raise ValueError("executable must be a bare executable name.")
        return self


class EnvironmentInspectionResult(BaseModel):
    kind: Literal["python_module", "executable"]
    name: str
    runtime_available: bool
    declared_by_project: bool | None = None
    environment: Literal["verification_sandbox"] = "verification_sandbox"
    warning: str | None = None
    error: str | None = None


class EnvironmentInspector(Protocol):
    def inspect(
        self, workspace_root: Path, request: EnvironmentInspectionArgs
    ) -> EnvironmentInspectionResult: ...


class InspectionSandboxRunner(Protocol):
    def run(self, context: SandboxExecutionContext) -> CommandResult: ...


class DockerEnvironmentInspector:
    """Run a Runtime-owned fixed probe in the verification Docker image."""

    def __init__(
        self,
        *,
        runner: InspectionSandboxRunner | None = None,
        profile: SandboxProfile | None = None,
    ) -> None:
        self._runner = runner or DockerRunner()
        self._profile = profile or SandboxProfile(workspace_write=False)

    def inspect(
        self, workspace_root: Path, request: EnvironmentInspectionArgs
    ) -> EnvironmentInspectionResult:
        root = workspace_root.resolve(strict=True)
        kind = "python_module" if request.python_module is not None else "executable"
        name = request.python_module or request.executable or ""
        argv = ("python", "-c", _FIXED_PROBE, kind, name)
        try:
            command = self._runner.run(
                SandboxExecutionContext(
                    argv=argv,
                    workspace_root=root,
                    cwd=root,
                    profile=self._profile,
                )
            )
        except Exception as error:  # noqa: BLE001
            command = CommandResult(
                status=CommandStatus.START_FAILED,
                argv=argv,
                cwd=root,
                error=f"{type(error).__name__}: {error}",
            )
        available = False
        probe_error = command.error
        if command.status is CommandStatus.SUCCESS and command.exit_code == 0:
            try:
                payload = json.loads(command.stdout)
                available = payload.get("runtime_available") is True
            except (json.JSONDecodeError, AttributeError) as error:
                probe_error = f"Invalid fixed-probe output: {error}"
        elif probe_error is None:
            probe_error = (
                command.stderr.strip()
                or command.stdout.strip()
                or f"fixed probe status={command.status.value}"
            )[:2_000]
        declared = _project_declaration(root, kind, name)
        warning = None
        if available and declared is not True:
            warning = (
                "Available in this verification sandbox but not declared by the "
                "project; relying on it is not portable."
            )
        return EnvironmentInspectionResult(
            kind=kind,
            name=name,
            runtime_available=available,
            declared_by_project=declared,
            warning=warning,
            error=probe_error,
        )


def _project_declaration(root: Path, kind: str, name: str) -> bool | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    project = payload.get("project")
    if not isinstance(project, dict):
        return None
    if kind == "executable":
        scripts = project.get("scripts")
        return name in scripts if isinstance(scripts, dict) else None
    dependencies = project.get("dependencies")
    optional = project.get("optional-dependencies")
    if dependencies is None and optional is None:
        return False
    declared: list[str] = []
    if isinstance(dependencies, list):
        declared.extend(item for item in dependencies if isinstance(item, str))
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                declared.extend(item for item in group if isinstance(item, str))
    wanted = name.split(".", 1)[0].lower().replace("_", "-")
    return any(
        re.split(r"[<>=!~;\s\[]", item, maxsplit=1)[0].lower().replace("_", "-")
        == wanted
        for item in declared
    )
