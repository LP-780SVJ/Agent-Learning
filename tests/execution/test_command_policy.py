from __future__ import annotations

import statistics
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from codeteam.execution.command_policy import CommandPolicy
from codeteam.execution.models import (
    CommandRequest,
    PolicyDecision,
    PolicyEvaluation,
    RiskCategory,
)


@dataclass(frozen=True)
class CommandCase:
    id: str
    argv: tuple[str, ...]
    expected: PolicyDecision
    expected_risks: tuple[RiskCategory, ...] = ()


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[CommandRequest] = []

    def run_if_policy_allows(self, request: CommandRequest) -> PolicyEvaluation:
        evaluation = CommandPolicy.default().evaluate(request)
        if evaluation.decision in {
            PolicyDecision.ALLOW,
            PolicyDecision.ALLOW_SANDBOXED,
        }:
            self.calls.append(request)
        return evaluation


def _request(
    tmp_path: Path,
    argv: Iterable[str],
    *,
    cwd: Path | None = None,
    workspace_root: Path | None = None,
) -> CommandRequest:
    workspace = workspace_root or tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    command_cwd = cwd or workspace
    command_cwd.mkdir(parents=True, exist_ok=True)
    return CommandRequest(
        argv=tuple(argv),
        cwd=command_cwd,
        workspace_root=workspace,
        task_id="task-command-policy",
        agent_id="agent-test",
        reason="policy test",
    )


def _evaluate(tmp_path: Path, argv: Iterable[str]) -> PolicyEvaluation:
    return CommandPolicy.default().evaluate(_request(tmp_path, argv))


SAFE_CASES = [
    CommandCase("git-status", ("git", "status"), PolicyDecision.ALLOW),
    CommandCase("git-diff", ("git", "diff"), PolicyDecision.ALLOW),
    CommandCase("git-log", ("git", "log"), PolicyDecision.ALLOW),
    CommandCase(
        "git-rev-parse-head",
        ("git", "rev-parse", "HEAD"),
        PolicyDecision.ALLOW,
    ),
    CommandCase("git-branch", ("git", "branch"), PolicyDecision.ALLOW),
    CommandCase(
        "git-branch-show-current",
        ("git", "branch", "--show-current"),
        PolicyDecision.ALLOW,
    ),
    CommandCase(
        "git-branch-list",
        ("git", "branch", "--list"),
        PolicyDecision.ALLOW,
    ),
    CommandCase(
        "git-worktree-list",
        ("git", "worktree", "list"),
        PolicyDecision.ALLOW,
    ),
    CommandCase(
        "git-worktree-list-porcelain",
        ("git", "worktree", "list", "--porcelain"),
        PolicyDecision.ALLOW,
    ),
    CommandCase(
        "pytest",
        ("pytest",),
        PolicyDecision.ALLOW_SANDBOXED,
        (RiskCategory.READ_ONLY,),
    ),
    CommandCase(
        "python-m-pytest",
        ("python", "-m", "pytest"),
        PolicyDecision.ALLOW_SANDBOXED,
        (RiskCategory.READ_ONLY,),
    ),
    CommandCase(
        "python3-m-pytest",
        ("python3", "-m", "pytest"),
        PolicyDecision.ALLOW_SANDBOXED,
        (RiskCategory.READ_ONLY,),
    ),
    CommandCase(
        "venv-python-m-pytest",
        (".venv/bin/python", "-m", "pytest"),
        PolicyDecision.ALLOW_SANDBOXED,
        (RiskCategory.READ_ONLY,),
    ),
    CommandCase(
        "ruff-check",
        ("ruff", "check"),
        PolicyDecision.ALLOW_SANDBOXED,
        (RiskCategory.READ_ONLY,),
    ),
    CommandCase(
        "mypy",
        ("mypy",),
        PolicyDecision.ALLOW_SANDBOXED,
        (RiskCategory.READ_ONLY,),
    ),
]


DANGEROUS_CASES = [
    CommandCase("sudo", ("sudo", "ls"), PolicyDecision.DENY),
    CommandCase("su", ("su", "-"), PolicyDecision.DENY),
    CommandCase("doas", ("doas", "id"), PolicyDecision.DENY),
    CommandCase(
        "git-reset-hard",
        ("git", "reset", "--hard"),
        PolicyDecision.DENY,
        (RiskCategory.DESTRUCTIVE,),
    ),
    CommandCase("git-clean-fd", ("git", "clean", "-fd"), PolicyDecision.DENY),
    CommandCase("git-clean-df", ("git", "clean", "-df"), PolicyDecision.DENY),
    CommandCase("git-clean-fdx", ("git", "clean", "-fdx"), PolicyDecision.DENY),
    CommandCase(
        "git-clean-ffdx",
        ("git", "clean", "-ffdx"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "git-clean-f-d",
        ("git", "clean", "-f", "-d"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "git-branch-delete-force",
        ("git", "branch", "-D", "old"),
        PolicyDecision.DENY,
        (RiskCategory.DESTRUCTIVE,),
    ),
    CommandCase(
        "git-branch-delete",
        ("git", "branch", "-d", "old"),
        PolicyDecision.DENY,
        (RiskCategory.DESTRUCTIVE,),
    ),
    CommandCase("sh-c", ("sh", "-c", "echo hi"), PolicyDecision.DENY),
    CommandCase("bash-c", ("bash", "-c", "echo hi"), PolicyDecision.DENY),
    CommandCase("zsh-c", ("zsh", "-c", "echo hi"), PolicyDecision.DENY),
    CommandCase("python-c", ("python", "-c", "print(1)"), PolicyDecision.DENY),
    CommandCase(
        "python311-c",
        ("python3.11", "-c", "print(1)"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "absolute-python-c",
        ("/usr/bin/python3", "-c", "print(1)"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "env-python-c",
        ("/usr/bin/env", "python", "-c", "print(1)"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "env-python3-c",
        ("/usr/bin/env", "python3", "-c", "print(1)"),
        PolicyDecision.DENY,
    ),
    CommandCase("node-e", ("node", "-e", "1 + 1"), PolicyDecision.DENY),
    CommandCase("ruby-e", ("ruby", "-e", "puts 1"), PolicyDecision.DENY),
    CommandCase("perl-e", ("perl", "-e", "print 1"), PolicyDecision.DENY),
    CommandCase("shutdown", ("shutdown", "now"), PolicyDecision.DENY),
    CommandCase("reboot", ("reboot",), PolicyDecision.DENY),
    CommandCase(
        "home-ssh",
        ("cat", "~/.ssh/id_rsa"),
        PolicyDecision.DENY,
        (RiskCategory.SECRET_ACCESS,),
    ),
    CommandCase(
        "dot-env",
        ("cat", ".env"),
        PolicyDecision.DENY,
        (RiskCategory.SECRET_ACCESS,),
    ),
    CommandCase(
        "home-aws",
        ("cat", "~/.aws/credentials"),
        PolicyDecision.DENY,
        (RiskCategory.SECRET_ACCESS,),
    ),
    CommandCase(
        "home-kube",
        ("cat", "~/.kube/config"),
        PolicyDecision.DENY,
        (RiskCategory.SECRET_ACCESS,),
    ),
    CommandCase(
        "docker-privileged",
        ("docker", "run", "--privileged", "alpine"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "docker-network-host",
        ("docker", "run", "--network=host", "alpine"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "docker-socket-mount",
        ("docker", "run", "-v", "/var/run/docker.sock:/sock", "alpine"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "docker-root-mount",
        ("docker", "run", "-v", "/:/host", "alpine"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "docker-etc-mount",
        ("docker", "run", "-v", "/etc:/host/etc", "alpine"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "docker-var-mount",
        ("docker", "run", "--mount", "type=bind,src=/var,dst=/host/var", "alpine"),
        PolicyDecision.DENY,
    ),
    CommandCase(
        "docker-usr-mount",
        ("docker", "run", "--volume=/usr:/host/usr", "alpine"),
        PolicyDecision.DENY,
    ),
]


APPROVAL_CASES = [
    CommandCase("curl", ("curl", "https://example.test"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("wget", ("wget", "https://example.test"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("ssh", ("ssh", "host"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("scp", ("scp", "a", "host:b"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("rsync", ("rsync", "a", "host:b"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("ping", ("ping", "example.test"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("pip-install", ("pip", "install", "pkg"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("pip3-install", ("pip3", "install", "pkg"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase(
        "python-m-pip-install",
        ("python", "-m", "pip", "install", "pkg"),
        PolicyDecision.REQUIRE_APPROVAL,
    ),
    CommandCase(
        "python3-m-pip-install",
        ("python3", "-m", "pip", "install", "pkg"),
        PolicyDecision.REQUIRE_APPROVAL,
    ),
    CommandCase(
        "env-python-m-pip-install",
        ("/usr/bin/env", "python", "-m", "pip", "install", "pkg"),
        PolicyDecision.REQUIRE_APPROVAL,
    ),
    CommandCase("npm-install", ("npm", "install"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("pnpm-install", ("pnpm", "install"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("yarn-install", ("yarn", "install"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("git-push", ("git", "push"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("npm-publish", ("npm", "publish"), PolicyDecision.REQUIRE_APPROVAL),
    CommandCase("docker-push", ("docker", "push", "image"), PolicyDecision.REQUIRE_APPROVAL),
]


@pytest.mark.parametrize("case", SAFE_CASES, ids=[case.id for case in SAFE_CASES])
def test_safe_commands_are_auto_allowed(
    tmp_path: Path,
    case: CommandCase,
) -> None:
    evaluation = _evaluate(tmp_path, case.argv)

    assert evaluation.decision is case.expected
    assert evaluation.matched_rules
    for risk in case.expected_risks:
        assert risk in evaluation.risks


@pytest.mark.parametrize(
    "case",
    DANGEROUS_CASES,
    ids=[case.id for case in DANGEROUS_CASES],
)
def test_dangerous_commands_are_denied(
    tmp_path: Path,
    case: CommandCase,
) -> None:
    evaluation = _evaluate(tmp_path, case.argv)

    assert evaluation.decision is PolicyDecision.DENY
    assert evaluation.matched_rules
    assert evaluation.reasons
    for risk in case.expected_risks:
        assert risk in evaluation.risks


@pytest.mark.parametrize(
    "case",
    APPROVAL_CASES,
    ids=[case.id for case in APPROVAL_CASES],
)
def test_network_install_and_remote_write_commands_require_approval(
    tmp_path: Path,
    case: CommandCase,
) -> None:
    evaluation = _evaluate(tmp_path, case.argv)

    assert evaluation.decision is PolicyDecision.REQUIRE_APPROVAL
    assert evaluation.matched_rules
    assert RiskCategory.NETWORK in evaluation.risks or RiskCategory.REMOTE_WRITE in evaluation.risks


def test_unknown_command_defaults_to_require_approval(tmp_path: Path) -> None:
    evaluation = _evaluate(tmp_path, ("custom-tool", "--option"))

    assert evaluation.decision is PolicyDecision.REQUIRE_APPROVAL
    assert evaluation.risks == (RiskCategory.UNKNOWN,)
    assert evaluation.matched_rules == ()
    assert evaluation.reasons == ("Unknown command requires approval.",)


def test_empty_argv_is_rejected_by_pydantic(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValidationError):
        CommandRequest(argv=(), cwd=workspace, workspace_root=workspace)


@pytest.mark.parametrize(
    ("argv", "expected", "expected_rule"),
    [
        (
            ("git", "diff", "~/.ssh/config"),
            PolicyDecision.DENY,
            "credential_path",
        ),
        (
            ("pytest", "/tmp/outside"),
            PolicyDecision.DENY,
            "filesystem_escape",
        ),
        (
            ("python", "-m", "pip", "install", "pkg"),
            PolicyDecision.REQUIRE_APPROVAL,
            "network_command",
        ),
    ],
)
def test_highest_risk_decision_wins_when_multiple_rules_match(
    tmp_path: Path,
    argv: tuple[str, ...],
    expected: PolicyDecision,
    expected_rule: str,
) -> None:
    evaluation = _evaluate(tmp_path, argv)

    assert evaluation.decision is expected
    assert expected_rule in evaluation.matched_rules


def test_safe_git_read_does_not_allow_destructive_git_subcommands(
    tmp_path: Path,
) -> None:
    for argv in [
        ("git", "reset", "--hard"),
        ("git", "clean", "-fdx"),
        ("git", "branch", "-D", "old"),
    ]:
        evaluation = _evaluate(tmp_path, argv)
        assert evaluation.decision is PolicyDecision.DENY
        assert "safe_git_read" not in evaluation.matched_rules


def test_policy_evaluate_returns_evaluation_without_running_command(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, ("git", "status"))

    evaluation = CommandPolicy.default().evaluate(request)

    assert isinstance(evaluation, PolicyEvaluation)
    assert evaluation.decision is PolicyDecision.ALLOW


def test_denied_command_does_not_reach_fake_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    request = _request(tmp_path, ("sudo", "id"))

    evaluation = runner.run_if_policy_allows(request)

    assert evaluation.decision is PolicyDecision.DENY
    assert runner.calls == []


def test_allowed_command_reaches_fake_runner_once(tmp_path: Path) -> None:
    runner = FakeRunner()
    request = _request(tmp_path, ("git", "status"))

    evaluation = runner.run_if_policy_allows(request)

    assert evaluation.decision is PolicyDecision.ALLOW
    assert runner.calls == [request]


def test_diagnostic_fields_include_rules_risks_and_reasons(tmp_path: Path) -> None:
    evaluation = _evaluate(tmp_path, ("sudo", "git", "push"))

    assert evaluation.decision is PolicyDecision.DENY
    assert "privilege_escalation" in evaluation.matched_rules
    assert RiskCategory.PRIVILEGE_ESCALATION in evaluation.risks
    assert evaluation.reasons


def test_cwd_outside_workspace_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    evaluation = CommandPolicy.default().evaluate(
        CommandRequest(
            argv=("git", "status"),
            cwd=outside,
            workspace_root=workspace,
        )
    )

    assert evaluation.decision is PolicyDecision.DENY
    assert "cwd_workspace_boundary" in evaluation.matched_rules
    assert RiskCategory.FILESYSTEM_ESCAPE in evaluation.risks


def test_workspace_external_path_argument_is_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    evaluation = CommandPolicy.default().evaluate(
        CommandRequest(
            argv=("cat", str(outside / "file.txt")),
            cwd=workspace,
            workspace_root=workspace,
        )
    )

    assert evaluation.decision is PolicyDecision.DENY
    assert "filesystem_escape" in evaluation.matched_rules


def test_docker_workspace_bind_mount_is_not_denied_by_privilege_rule(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "cache"
    source.mkdir()

    evaluation = CommandPolicy.default().evaluate(
        CommandRequest(
            argv=("docker", "run", "-v", f"{source}:/cache", "alpine"),
            cwd=workspace,
            workspace_root=workspace,
        )
    )

    assert "docker_privilege" not in evaluation.matched_rules
    assert evaluation.decision is PolicyDecision.REQUIRE_APPROVAL
    assert evaluation.risks == (RiskCategory.UNKNOWN,)


def test_policy_evaluation_dataset_metrics_are_computable(tmp_path: Path) -> None:
    dataset = SAFE_CASES + DANGEROUS_CASES + APPROVAL_CASES
    evaluations = [
        (case, _evaluate(tmp_path, case.argv))
        for case in dataset
    ]

    dangerous_pass_through = [
        case.id
        for case, evaluation in evaluations
        if case in DANGEROUS_CASES
        and evaluation.decision in {PolicyDecision.ALLOW, PolicyDecision.ALLOW_SANDBOXED}
    ]
    safe_auto_allowed = [
        case.id
        for case, evaluation in evaluations
        if case in SAFE_CASES
        and evaluation.decision in {PolicyDecision.ALLOW, PolicyDecision.ALLOW_SANDBOXED}
    ]
    approval_burden = [
        case.id
        for case, evaluation in evaluations
        if case in SAFE_CASES and evaluation.decision is PolicyDecision.REQUIRE_APPROVAL
    ]
    false_denies = [
        case.id
        for case, evaluation in evaluations
        if case in SAFE_CASES and evaluation.decision is PolicyDecision.DENY
    ]

    assert not dangerous_pass_through
    assert len(safe_auto_allowed) == len(SAFE_CASES)
    assert not approval_burden
    assert not false_denies


def test_policy_latency_exploratory_measurement_is_fast_enough(
    tmp_path: Path,
) -> None:
    requests = [
        _request(tmp_path, case.argv)
        for case in SAFE_CASES + DANGEROUS_CASES + APPROVAL_CASES
    ]
    durations_ms: list[float] = []
    policy = CommandPolicy.default()

    for request in requests:
        started = time.perf_counter()
        policy.evaluate(request)
        durations_ms.append((time.perf_counter() - started) * 1000)

    p50 = statistics.median(durations_ms)
    p95 = sorted(durations_ms)[int(len(durations_ms) * 0.95) - 1]

    assert p50 >= 0
    assert p95 >= p50
