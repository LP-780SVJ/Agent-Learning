from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol

from codeteam.execution.models import (
    CommandRequest,
    PolicyDecision,
    RiskCategory,
    RuleResult,
)


class PolicyRule(Protocol):
    """CommandPolicy 中每条规则都要遵守的接口。"""

    name: str

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        """检查一条命令请求。

        返回:
        - RuleResult: 当前规则命中，并给出决策
        - None: 当前规则不关心这条命令
        """
        ...


def _command_name(request: CommandRequest) -> str:
    return Path(request.argv[0]).name.lower()


def _basename(value: str) -> str:
    return Path(value).name.lower()


def _is_python_command(command: str) -> bool:
    suffix = command.removeprefix("python")
    return command == "python" or (command.startswith("python") and suffix[:1].isdigit())


def _effective_command_and_args(request: CommandRequest) -> tuple[str, tuple[str, ...]]:
    """Return the real command when argv starts with /usr/bin/env."""
    command = _command_name(request)
    arguments = request.argv[1:]

    if command != "env":
        return command, tuple(arguments)

    for index, argument in enumerate(arguments):
        if argument.startswith("-"):
            continue
        if "=" in argument and not argument.startswith(("/", "~")):
            continue
        return _basename(argument), tuple(arguments[index + 1:])

    return command, tuple(arguments)


def _has_combined_short_flags(argument: str, required_flags: frozenset[str]) -> bool:
    if not argument.startswith("-") or argument.startswith("--"):
        return False

    return required_flags.issubset(set(argument[1:]))


def _git_clean_has_force_and_directory_flags(arguments: tuple[str, ...]) -> bool:
    short_flags: set[str] = set()

    for argument in arguments:
        if argument.startswith("--"):
            if argument == "--force":
                short_flags.add("f")
            continue

        if argument.startswith("-"):
            short_flags.update(argument[1:])

    return {"f", "d"}.issubset(short_flags)


class PrivilegeEscalationRule:
    name = "privilege_escalation"

    dangerous_commands: ClassVar[frozenset[str]] = frozenset({
        "sudo",
        "su",
        "doas",
    })

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command = _command_name(request)

        if command not in self.dangerous_commands:
            return None

        return RuleResult(
            rule_name=self.name,
            decision=PolicyDecision.DENY,
            risks=(RiskCategory.PRIVILEGE_ESCALATION,),
            reason=f"Privilege escalation command is not allowed: {command}",
        )


class GitDestructiveRule:
    name = "git_destructive"

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        argv = tuple(argument.lower() for argument in request.argv)
        command = _command_name(request)

        if command != "git":
            return None

        if len(argv) >= 3 and argv[1] == "reset" and "--hard" in argv[2:]:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.DENY,
                risks=(RiskCategory.DESTRUCTIVE,),
                reason="git reset --hard is destructive.",
            )

        if len(argv) >= 3 and argv[1] == "clean" and _git_clean_has_force_and_directory_flags(argv[2:]):
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.DENY,
                risks=(RiskCategory.DESTRUCTIVE,),
                reason="git clean with force flags is destructive.",
            )

        return None


class ShellInterpreterRule:
    name = "shell_interpreter"

    shell_commands: ClassVar[frozenset[str]] = frozenset({
        "sh",
        "bash",
        "zsh",
        "fish",
        "dash",
        "ksh",
    })

    interpreter_flags: ClassVar[dict[str, frozenset[str]]] = {
        "python": frozenset({"-c"}),
        "python3": frozenset({"-c"}),
        "node": frozenset({"-e", "-p"}),
        "ruby": frozenset({"-e"}),
        "perl": frozenset({"-e"}),
        "php": frozenset({"-r"}),
    }

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command, raw_arguments = _effective_command_and_args(request)
        arguments = {argument.lower() for argument in raw_arguments}

        if command in self.shell_commands and "-c" in arguments:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.DENY,
                risks=(RiskCategory.SHELL_INTERPRETER,),
                reason=f"Shell string execution is not allowed: {command} -c",
            )

        flags = self.interpreter_flags.get(command)
        if flags is None and _is_python_command(command):
            flags = self.interpreter_flags["python"]

        if flags is not None and arguments & flags:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.DENY,
                risks=(RiskCategory.SHELL_INTERPRETER,),
                reason=f"Interpreter string execution is not allowed: {command}",
            )

        return None


class SystemControlRule:
    name = "system_control"

    system_commands: ClassVar[frozenset[str]] = frozenset({
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
    })

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command = _command_name(request)

        if command not in self.system_commands:
            return None

        return RuleResult(
            rule_name=self.name,
            decision=PolicyDecision.DENY,
            risks=(RiskCategory.DESTRUCTIVE,),
            reason=f"System control command is not allowed: {command}",
        )

def _path_like_arguments(request: CommandRequest) -> tuple[str, ...]:
    path_arguments: list[str] = []

    for argument in request.argv[1:]:
        if argument.startswith("-"):
            continue

        if (
            argument.startswith(("/", "~"))
            or argument in {".", ".."}
            or "/" in argument
            or "\\" in argument
        ):
            path_arguments.append(argument)

    return tuple(path_arguments)


def _resolve_argument_path(request: CommandRequest, argument: str) -> Path:
    raw_path = Path(argument).expanduser()

    if raw_path.is_absolute():
        return raw_path.resolve(strict=False)

    return (request.cwd / raw_path).resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


class CwdWorkspaceRule:
    name = "cwd_workspace_boundary"

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        cwd = request.cwd.resolve(strict=False)
        workspace_root = request.workspace_root.resolve(strict=False)

        if _is_relative_to(cwd, workspace_root):
            return None

        return RuleResult(
            rule_name=self.name,
            decision=PolicyDecision.DENY,
            risks=(RiskCategory.FILESYSTEM_ESCAPE,),
            reason=f"Command cwd escapes workspace: {request.cwd}",
        )


class FilesystemEscapeRule:
    name = "filesystem_escape"

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        workspace_root = request.workspace_root.resolve(strict=False)

        for argument in _path_like_arguments(request):
            candidate = _resolve_argument_path(request, argument)

            if not _is_relative_to(candidate, workspace_root):
                return RuleResult(
                    rule_name=self.name,
                    decision=PolicyDecision.DENY,
                    risks=(RiskCategory.FILESYSTEM_ESCAPE,),
                    reason=f"Path argument escapes workspace: {argument}",
                )

        return None


class CredentialPathRule:
    name = "credential_path"

    credential_markers: ClassVar[frozenset[str]] = frozenset({
        ".ssh",
        ".aws",
        ".gnupg",
        ".kube",
        ".docker",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".env",
    })

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        for argument in _path_like_arguments(request):
            lowered_parts = {
                part.lower()
                for part in Path(argument).expanduser().parts
            }

            if lowered_parts & self.credential_markers:
                return RuleResult(
                    rule_name=self.name,
                    decision=PolicyDecision.DENY,
                    risks=(RiskCategory.SECRET_ACCESS,),
                    reason=f"Credential path access is not allowed: {argument}",
                )

        return None


class NetworkCommandRule:
    name = "network_command"

    network_commands: ClassVar[frozenset[str]] = frozenset({
        "curl",
        "wget",
        "ssh",
        "scp",
        "rsync",
        "ping",
    })

    package_install_commands: ClassVar[frozenset[tuple[str, str]]] = frozenset({
        ("pip", "install"),
        ("pip3", "install"),
        ("npm", "install"),
        ("pnpm", "install"),
        ("yarn", "install"),
    })

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command, raw_arguments = _effective_command_and_args(request)
        arguments = tuple(argument.lower() for argument in raw_arguments)

        if command in self.network_commands:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.NETWORK,),
                reason=f"Network command requires approval: {command}",
            )

        if len(arguments) >= 1 and (command, arguments[0]) in self.package_install_commands:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.NETWORK,),
                reason=f"Package install may access network: {command} {arguments[0]}",
            )

        if (
            _is_python_command(command)
            and len(arguments) >= 3
            and arguments[0] == "-m"
            and arguments[1] in {"pip", "pip3"}
            and arguments[2] == "install"
        ):
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.NETWORK,),
                reason="Python pip install may access network.",
            )

        return None


class RemoteWriteRule:
    name = "remote_write"

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command = _command_name(request)
        argv = tuple(argument.lower() for argument in request.argv)

        if command == "git" and len(argv) >= 2 and argv[1] == "push":
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.REMOTE_WRITE, RiskCategory.NETWORK),
                reason="git push writes to a remote repository.",
            )

        if command in {"npm", "pnpm", "yarn"} and "publish" in argv[1:]:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.REMOTE_WRITE, RiskCategory.NETWORK),
                reason=f"{command} publish writes to a remote registry.",
            )

        if command == "docker" and "push" in argv[1:]:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.REQUIRE_APPROVAL,
                risks=(RiskCategory.REMOTE_WRITE, RiskCategory.NETWORK),
                reason="docker push writes to a remote registry.",
            )

        return None


class DockerPrivilegeRule:
    name = "docker_privilege"

    dangerous_flags: ClassVar[frozenset[str]] = frozenset({
        "--privileged",
        "--network=host",
        "--pid=host",
        "--ipc=host",
    })

    dangerous_host_paths: ClassVar[frozenset[str]] = frozenset({
        "/var/run/docker.sock",
        "/",
        "/etc",
        "/var",
        "/usr",
    })

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command = _command_name(request)
        argv = tuple(argument.lower() for argument in request.argv)

        if command != "docker":
            return None

        if set(argv[1:]) & self.dangerous_flags:
            return RuleResult(
                rule_name=self.name,
                decision=PolicyDecision.DENY,
                risks=(RiskCategory.PRIVILEGE_ESCALATION,),
                reason="Docker privileged or host namespace flags are not allowed.",
            )

        for host_path in _docker_mount_host_paths(request.argv[1:]):
            resolved_host_path = _resolve_argument_path(request, host_path)

            if _is_sensitive_docker_host_path(
                resolved_host_path,
                self.dangerous_host_paths,
            ):
                return RuleResult(
                    rule_name=self.name,
                    decision=PolicyDecision.DENY,
                    risks=(RiskCategory.PRIVILEGE_ESCALATION,),
                    reason=f"Docker host mount target is too sensitive: {host_path}",
                )

        return None


def _docker_mount_host_paths(arguments: tuple[str, ...]) -> tuple[str, ...]:
    host_paths: list[str] = []
    pending_mount_flag = False

    for argument in arguments:
        lowered = argument.lower()

        if pending_mount_flag:
            host_path = _docker_mount_source_from_spec(argument)
            if host_path is not None:
                host_paths.append(host_path)
            pending_mount_flag = False
            continue

        if lowered in {"-v", "--volume", "--mount"}:
            pending_mount_flag = True
            continue

        if lowered.startswith("--volume="):
            spec = argument.split("=", 1)[1]
            host_path = _docker_mount_source_from_spec(spec)
            if host_path is not None:
                host_paths.append(host_path)
            continue

        if lowered.startswith("--mount="):
            spec = argument.split("=", 1)[1]
            host_path = _docker_mount_source_from_spec(spec)
            if host_path is not None:
                host_paths.append(host_path)

    return tuple(host_paths)


def _is_sensitive_docker_host_path(
    host_path: Path,
    sensitive_paths: frozenset[str],
) -> bool:
    for sensitive_path_text in sensitive_paths:
        sensitive_path = Path(sensitive_path_text).resolve(strict=False)

        if sensitive_path_text == "/" and host_path == sensitive_path:
            return True

        if sensitive_path_text != "/" and _is_relative_to(host_path, sensitive_path):
            return True

    return False


def _docker_mount_source_from_spec(spec: str) -> str | None:
    parts = spec.split(",")
    key_value_parts = {
        key.strip().lower(): value.strip()
        for part in parts
        if "=" in part
        for key, value in [part.split("=", 1)]
    }

    for key in ("src", "source"):
        if key in key_value_parts:
            return key_value_parts[key]

    if ":" in spec:
        return spec.split(":", 1)[0]

    return None


class SafeGitReadRule:
    name = "safe_git_read"

    safe_subcommands: ClassVar[frozenset[str]] = frozenset({
        "status",
        "diff",
        "show",
        "log",
        "rev-parse",
        "worktree",
    })

    safe_branch_arguments: ClassVar[frozenset[str]] = frozenset({
        "--show-current",
        "--list",
    })

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command = _command_name(request)
        argv = tuple(argument.lower() for argument in request.argv)

        if command != "git":
            return None

        if len(argv) < 2:
            return None

        subcommand = argv[1]

        if subcommand == "branch":
            if len(argv) == 2 or set(argv[2:]).issubset(self.safe_branch_arguments):
                return RuleResult(
                    rule_name=self.name,
                    decision=PolicyDecision.ALLOW,
                    risks=(RiskCategory.READ_ONLY,),
                    reason="Safe git read command: git branch",
                )
            return None

        if subcommand not in self.safe_subcommands:
            return None

        if subcommand == "worktree" and len(argv) >= 3 and argv[2] != "list":
            return None

        return RuleResult(
            rule_name=self.name,
            decision=PolicyDecision.ALLOW,
            risks=(RiskCategory.READ_ONLY,),
            reason=f"Safe git read command: git {subcommand}",
        )


class SafeDevCommandRule:
    name = "safe_dev_command"

    def evaluate(
        self,
        request: CommandRequest,
    ) -> RuleResult | None:
        command, raw_arguments = _effective_command_and_args(request)
        arguments = tuple(argument.lower() for argument in raw_arguments)

        if command == "pytest":
            return self._allow_sandboxed("pytest")

        if _is_python_command(command) and len(arguments) >= 2 and arguments[0] == "-m" and arguments[1] == "pytest":
            return self._allow_sandboxed(f"{command} -m pytest")

        if command == "ruff" and arguments[:1] == ("check",):
            return self._allow_sandboxed("ruff check")

        if command == "mypy":
            return self._allow_sandboxed("mypy")

        return None

    def _allow_sandboxed(self, command_description: str) -> RuleResult:
        return RuleResult(
            rule_name=self.name,
            decision=PolicyDecision.ALLOW_SANDBOXED,
            risks=(RiskCategory.READ_ONLY,),
            reason=f"Development command should run in sandbox: {command_description}",
        )
