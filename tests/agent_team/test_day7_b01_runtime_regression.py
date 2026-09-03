from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent.runtime_models import CodingAgentRunRequest, RuntimeStatus
from codeteam.agent_team.team_planning import DeterministicSingleNodePlanner
from codeteam.agent_team.team_runtime import TeamCodingRuntime
from codeteam.agent_team.team_runtime_provider import LocalTeamRuntimeProvider
from codeteam.agent_team.worker_executor import WorkerExecutor
from codeteam.application.build_context import CodeContextReport
from codeteam.context.models import CompressionLevel
from codeteam.execution.models import CommandResult, CommandStatus
from codeteam.execution.safe_execution_service import SafeExecutionService
from codeteam.llm.base import ModelFinishState, ModelRequest, ModelTurn
from codeteam.sandbox.preflight import SandboxPreflightResult
from codeteam.sandbox.verification_preflight import (
    VerificationEnvironmentCheckResult,
    VerificationEnvironmentMetadata,
)
from codeteam.schemas.tool_calls import ToolCall


class ScriptedB01Model:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        replacement = {
            "path": "src/auth/api.py",
            "old_text": (
                "        except RefreshTokenExpired:\n"
                '            return {"status": 401, '
                '"error": "internal server error"}'
            ),
            "new_text": (
                "        except RefreshTokenExpired as error:\n"
                '            return {"status": 401, "error": str(error)}'
            ),
            "expected_replacements": 1,
        }
        self.turns = [
            _turn(1, "apply_patch", {"replacements": [replacement]}),
            _turn(
                2,
                "run_tests",
                {
                    "argv": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/task_verification/test_b01.py",
                        "-q",
                    ]
                },
            ),
            _turn(
                3,
                "run_tests",
                {"argv": ["python", "-m", "pytest", "tests/auth", "-q"]},
            ),
            _turn(4, "git_diff", {}),
            _turn(5, "submit_result", {"summary": "fixed expired token mapping"}),
        ]

    def turn(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        return self.turns.pop(0)


class WorkingSetAwareB01Model:
    """Act only after two exploration batches remain visible together."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def turn(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        index = len(self.requests)
        if index == 1:
            return _turn_batch(
                (1, "read_file", {"path": "src/auth/exceptions.py"}),
                (2, "read_file", {"path": "src/auth/tokens.py"}),
                (3, "read_file", {"path": "src/auth/repository.py"}),
                (4, "list_files", {"path": "."}),
            )
        if index == 2:
            return _turn_batch(
                (5, "read_file", {"path": "src/auth/api.py"}),
                (6, "read_file", {"path": "src/auth/service.py"}),
                (
                    7,
                    "read_file",
                    {"path": "tests/task_verification/test_b01.py"},
                ),
                (8, "read_file", {"path": "docs/auth.md"}),
            )
        if index == 3:
            visible = _visible_working_set_paths(request)
            required = {
                "src/auth/api.py",
                "src/auth/service.py",
                "src/auth/exceptions.py",
                "src/auth/tokens.py",
            }
            if not required <= visible:
                return _turn_batch(
                    (9, "read_file", {"path": "src/auth/exceptions.py"}),
                    (10, "read_file", {"path": "src/auth/tokens.py"}),
                )
            return _turn(
                9,
                "apply_patch",
                {
                    "replacements": [
                        {
                            "path": "src/auth/api.py",
                            "old_text": "except RefreshTokenExpired:\n",
                            "new_text": "except RefreshTokenExpired as error:\n",
                            "expected_replacements": 1,
                        },
                        {
                            "path": "src/auth/api.py",
                            "old_text": (
                                'return {"status": 401, '
                                '"error": "internal server error"}'
                            ),
                            "new_text": (
                                'return {"status": 401, "error": str(error)}'
                            ),
                            "expected_replacements": 1,
                        },
                    ]
                },
            )
        if index == 4:
            return _turn(
                10,
                "run_tests",
                {
                    "argv": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/task_verification/test_b01.py",
                        "-q",
                    ]
                },
            )
        if index == 5:
            return _turn(
                11,
                "run_tests",
                {"argv": ["python", "-m", "pytest", "tests/auth", "-q"]},
            )
        if index == 6:
            return _turn(12, "git_diff", {})
        return _turn(13, "submit_result", {"summary": "fixed after exploration"})


class CompactionControlAwareB01Model:
    """Reproduce diagnosis loss followed by a cached exploration turn."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.recovery_summary: dict[str, object] | None = None
        self.post_patch_summary: dict[str, object] | None = None

    def turn(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        index = len(self.requests)
        if index == 1:
            return _turn_batch(
                (1, "read_file", {"path": "src/auth/exceptions.py"}),
                (2, "read_file", {"path": "src/auth/tokens.py"}),
                (3, "read_file", {"path": "src/auth/repository.py"}),
                (4, "list_files", {"path": "."}),
            )
        if index == 2:
            return _turn_batch(
                (5, "read_file", {"path": "src/auth/api.py"}),
                (6, "read_file", {"path": "src/auth/service.py"}),
                (7, "read_file", {"path": "tests/auth/test_refresh_flow.py"}),
                (8, "read_file", {"path": "src/auth/AGENTS.md"}),
            )
        if index == 3:
            return _turn_with_text(
                9,
                "read_file",
                {"path": "tests/task_verification/test_b01.py"},
                text=(
                    "The bug is clear in src/auth/api.py: RefreshTokenExpired is "
                    "mapped to internal server error. I will inspect the public "
                    "contract once, then patch that handler."
                ),
            )
        if index == 4:
            # Deliberately mimic the real provider forgetting its own diagnosis.
            return _turn_batch(
                (10, "read_file", {"path": "src/auth/api.py"}),
                (11, "read_file", {"path": "src/auth/exceptions.py"}),
            )
        if index == 5:
            summary = _structured_summary(request)
            self.recovery_summary = summary
            control = summary.get("control_state")
            working_set = summary.get("working_set")
            recovered = (
                isinstance(summary.get("latest_agent_intent"), str)
                and "bug is clear" in str(summary["latest_agent_intent"]).lower()
                and isinstance(control, dict)
                and "no_progress_advisory" in control
                and isinstance(working_set, list)
                and any(
                    isinstance(item, dict)
                    and isinstance(item.get("observation_state"), dict)
                    and item["observation_state"].get("duplicate") is True
                    for item in working_set
                )
            )
            if not recovered:
                return _turn_batch(
                    (12, "read_file", {"path": "src/auth/api.py"}),
                    (13, "read_file", {"path": "src/auth/exceptions.py"}),
                )
            return _turn(
                12,
                "apply_patch",
                {
                    "replacements": [
                        {
                            "path": "src/auth/api.py",
                            "old_text": "except RefreshTokenExpired:\n",
                            "new_text": "except RefreshTokenExpired as error:\n",
                            "expected_replacements": 1,
                        },
                        {
                            "path": "src/auth/api.py",
                            "old_text": (
                                'return {"status": 401, '
                                '"error": "internal server error"}'
                            ),
                            "new_text": (
                                'return {"status": 401, "error": str(error)}'
                            ),
                            "expected_replacements": 1,
                        },
                    ]
                },
            )
        if index == 6:
            summary = _structured_summary(request)
            self.post_patch_summary = summary
            workspace_change = summary.get("workspace_change")
            if not (
                summary.get("next_required_action") == "run_task_verification"
                and isinstance(workspace_change, dict)
                and workspace_change.get("status") == "patch_applied"
                and summary.get("latest_agent_intent") is None
            ):
                return _turn(
                    14,
                    "apply_patch",
                    {
                        "replacements": [
                            {
                                "path": "src/auth/api.py",
                                "old_text": "except RefreshTokenExpired:\n",
                                "new_text": "except RefreshTokenExpired as error:\n",
                                "expected_replacements": 1,
                            }
                        ]
                    },
                )
            return _turn(
                14,
                "run_tests",
                {
                    "argv": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/task_verification/test_b01.py",
                        "-q",
                    ]
                },
            )
        if index == 7:
            summary = _structured_summary(request)
            if summary.get("next_required_action") != "run_regression_verification":
                return _turn(
                    15,
                    "run_tests",
                    {
                        "argv": [
                            "python",
                            "-m",
                            "pytest",
                            "tests/task_verification/test_b01.py",
                            "-q",
                        ]
                    },
                )
            return _turn(
                15,
                "run_tests",
                {"argv": ["python", "-m", "pytest", "tests/auth", "-q"]},
            )
        if index == 8:
            return _turn(16, "git_diff", {})
        return _turn(17, "submit_result", {"summary": "fixed after recovery"})


class PassingSandbox:
    def run(self, context) -> CommandResult:
        return CommandResult(
            status=CommandStatus.SUCCESS,
            argv=context.argv,
            cwd=context.cwd,
            exit_code=0,
            stdout="passed",
        )


class AvailableSandboxPreflight:
    def check(self, workspace_root: Path) -> SandboxPreflightResult:
        del workspace_root
        return SandboxPreflightResult(available=True)


class AvailableVerificationPreflight:
    def check(self, workspace_root: Path, requirement):
        del workspace_root
        return VerificationEnvironmentCheckResult(
            available=True,
            category="verification_toolchain_ready",
            metadata=VerificationEnvironmentMetadata(
                configured_image="test-sandbox",
                python_version="Python test-double",
                pytest_version="pytest test-double",
                capabilities=requirement.capabilities,
            ),
        )


class B01Context:
    def execute(self, **kwargs):
        root = kwargs["repository_root"]
        content = (root / "src/auth/api.py").read_text(encoding="utf-8")
        return SimpleNamespace(
            repo_map="src/auth/api.py\ntests/task_verification/test_b01.py",
            code_context=[
                CodeContextReport(
                    path="src/auth/api.py",
                    compression_level=CompressionLevel.FULL_FILE.value,
                    token_count=80,
                    content=content,
                )
            ],
            applicable_instructions=[],
            test_commands=[],
            diagnostics=[],
        )


def _turn(index: int, name: str, arguments: dict[str, object]) -> ModelTurn:
    return ModelTurn(
        tool_calls=(
            ToolCall(
                provider_call_id=f"provider-call-{index}",
                name=name,
                arguments=arguments,
            ),
        ),
        finish_state=ModelFinishState.TOOL_CALLS,
        model="mock-model",
    )


def _turn_with_text(
    index: int,
    name: str,
    arguments: dict[str, object],
    *,
    text: str,
) -> ModelTurn:
    return _turn(index, name, arguments).model_copy(update={"text": text})


def _turn_batch(*calls: tuple[int, str, dict[str, object]]) -> ModelTurn:
    return ModelTurn(
        tool_calls=tuple(
            ToolCall(
                provider_call_id=f"provider-call-{index}",
                name=name,
                arguments=arguments,
            )
            for index, name, arguments in calls
        ),
        finish_state=ModelFinishState.TOOL_CALLS,
        model="mock-model",
    )


def _visible_working_set_paths(request: ModelRequest) -> set[str]:
    paths: set[str] = set()
    for message in request.messages:
        if message.role != "user" or not message.content:
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        summary = payload.get("structured_context_summary")
        if not isinstance(summary, dict):
            continue
        working_set = summary.get("working_set")
        if not isinstance(working_set, list):
            continue
        for item in working_set:
            if not isinstance(item, dict) or item.get("tool") != "read_file":
                continue
            arguments = item.get("arguments")
            if isinstance(arguments, dict) and isinstance(arguments.get("path"), str):
                paths.add(arguments["path"])
    return paths


def _structured_summary(request: ModelRequest) -> dict[str, object]:
    for message in request.messages:
        if message.role != "user" or not message.content:
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        summary = payload.get("structured_context_summary")
        if isinstance(summary, dict):
            return summary
    return {}


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        shell=False,
        timeout=10,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "src/auth").mkdir(parents=True)
    (root / "src/auth/api.py").write_text(
        "from .exceptions import RefreshTokenExpired\n\n"
        "class AuthController:\n"
        "    def refresh(self, service, token):\n"
        "        try:\n"
        "            return service.refresh_session(token)\n"
        "        except RefreshTokenExpired:\n"
        '            return {"status": 401, "error": "internal server error"}\n',
        encoding="utf-8",
    )
    supporting_files = {
        "src/auth/exceptions.py": (
            "class RefreshTokenExpired(Exception):\n    pass\n" + "# contract\n" * 80
        ),
        "src/auth/tokens.py": "def decode_refresh_token(token):\n    return token\n" + "# token\n" * 80,
        "src/auth/repository.py": "class SessionRepository:\n    pass\n" + "# persistence\n" * 80,
        "src/auth/service.py": "class AuthService:\n    pass\n" + "# service\n" * 80,
        "tests/task_verification/test_b01.py": "def test_expired_contract():\n    pass\n" + "# public oracle\n" * 80,
        "docs/auth.md": "# Authentication\n" + "expired token contract\n" * 80,
        "AGENTS.md": "Run tests: `python -m pytest tests/auth -q`\n",
    }
    for relative, content in supporting_files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "CodeTeam Tests")
    _git(root, "config", "user.email", "codeteam-tests@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fault baseline")
    return root


def test_team_b01_reaches_patch_verification_diff_and_completion(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    model = ScriptedB01Model()
    single_runtime = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=PassingSandbox()),
        context_service=B01Context(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=AvailableVerificationPreflight(),
    )
    runtime = TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(single_runtime),
        runtime_provider=LocalTeamRuntimeProvider(tmp_path / "team-state"),
        max_workers=1,
    )

    result = runtime.run_team(
        CodingAgentRunRequest(
            task_id="B01",
            task="Fix the expired refresh token error mapping.",
            workspace_root=root,
            provider_id="scripted",
            model_id="mock-model",
            checkpoint_state_root=tmp_path / "checkpoints",
            task_verification_commands=(
                (
                    "python",
                    "-m",
                    "pytest",
                    "tests/task_verification/test_b01.py",
                    "-q",
                ),
            ),
            verification_commands=(
                ("python", "-m", "pytest", "tests/auth", "-q"),
            ),
            max_steps=20,
            max_tool_calls=40,
        )
    )

    assert result.runtime_result.status is RuntimeStatus.COMPLETED
    assert result.runtime_result.changed_files == ("src/auth/api.py",)
    assert result.runtime_result.patch_attempts == 1
    assert "str(error)" in result.runtime_result.diff
    assert len(model.requests) == 5
    task_dirs = list((tmp_path / "checkpoints" / "tasks").iterdir())
    assert len(task_dirs) == 1
    assert re.fullmatch(r"[A-Za-z0-9._-]+", task_dirs[0].name)
    assert ":" not in task_dirs[0].name
    first_system = json.loads(model.requests[0].messages[0].content or "{}")
    assert "tools" not in first_system
    assert first_system["tool_catalog"]


def test_team_b01_low_budget_retains_cross_turn_working_set_and_completes(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    model = WorkingSetAwareB01Model()
    single_runtime = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=PassingSandbox()),
        context_service=B01Context(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=AvailableVerificationPreflight(),
    )
    runtime = TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(single_runtime),
        runtime_provider=LocalTeamRuntimeProvider(tmp_path / "team-state-working-set"),
        max_workers=1,
    )

    result = runtime.run_team(
        CodingAgentRunRequest(
            task_id="B01-working-set",
            task="Fix the expired refresh token error mapping.",
            workspace_root=root,
            provider_id="scripted",
            model_id="mock-model",
            checkpoint_state_root=tmp_path / "checkpoints-working-set",
            task_verification_commands=(
                (
                    "python",
                    "-m",
                    "pytest",
                    "tests/task_verification/test_b01.py",
                    "-q",
                ),
            ),
            verification_commands=(
                ("python", "-m", "pytest", "tests/auth", "-q"),
            ),
            context_budget=4096,
            max_steps=20,
            max_tool_calls=40,
        )
    )

    runtime_result = result.runtime_result
    assert runtime_result.status is RuntimeStatus.COMPLETED
    assert runtime_result.changed_files == ("src/auth/api.py",)
    assert runtime_result.patch_attempts == 1
    assert len(model.requests) == 7
    assert _visible_working_set_paths(model.requests[2]) >= {
        "src/auth/api.py",
        "src/auth/service.py",
        "src/auth/exceptions.py",
        "src/auth/tokens.py",
    }
    assert any(item.compaction_applied for item in runtime_result.model_requests)
    third_request = runtime_result.model_requests[2]
    assert set(third_request.visible_read_paths) >= {
        "src/auth/api.py",
        "src/auth/service.py",
        "src/auth/exceptions.py",
        "src/auth/tokens.py",
    }


def test_team_b01_recovers_intent_and_control_after_compacted_duplicate_turn(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    model = CompactionControlAwareB01Model()
    single_runtime = CodingAgentRuntime(
        model_client=model,
        safe_execution=SafeExecutionService(sandbox_runner=PassingSandbox()),
        context_service=B01Context(),
        sandbox_preflight=AvailableSandboxPreflight(),
        verification_preflight=AvailableVerificationPreflight(),
    )
    runtime = TeamCodingRuntime(
        planner=DeterministicSingleNodePlanner(),
        worker_executor=WorkerExecutor(single_runtime),
        runtime_provider=LocalTeamRuntimeProvider(tmp_path / "team-state-control"),
        max_workers=1,
    )

    result = runtime.run_team(
        CodingAgentRunRequest(
            task_id="B01-control-recovery",
            task="Fix the expired refresh token error mapping.",
            workspace_root=root,
            provider_id="scripted",
            model_id="mock-model",
            checkpoint_state_root=tmp_path / "checkpoints-control",
            task_verification_commands=(
                (
                    "python",
                    "-m",
                    "pytest",
                    "tests/task_verification/test_b01.py",
                    "-q",
                ),
            ),
            verification_commands=(
                ("python", "-m", "pytest", "tests/auth", "-q"),
            ),
            context_budget=4096,
            max_steps=20,
            max_tool_calls=40,
        )
    )

    assert result.runtime_result.status is RuntimeStatus.COMPLETED
    assert result.runtime_result.changed_files == ("src/auth/api.py",)
    assert result.runtime_result.patch_attempts == 1
    assert model.recovery_summary is not None
    assert model.recovery_summary["control_state"]
    assert model.post_patch_summary is not None
    assert model.post_patch_summary["next_required_action"] == (
        "run_task_verification"
    )
    assert any(item.compaction_applied for item in result.runtime_result.model_requests)
