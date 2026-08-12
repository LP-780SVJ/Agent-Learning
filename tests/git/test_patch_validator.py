from __future__ import annotations

import ast
import inspect
from types import ModuleType

import pytest

import codeteam.git.patch as patch_module
import codeteam.git.workspace as workspace_module
from codeteam.git.models import PatchStatus
from codeteam.git.patch import PatchValidator
from codeteam.git.workspace import GitWorkspace

from .conftest import GitRepoFactory, make_patch, repository_state, write_file


def test_empty_patch_is_rejected_without_modifying_repository(
    git_repo_factory: GitRepoFactory,
) -> None:
    repo = git_repo_factory({"file.txt": "unchanged\n"})
    before = repository_state(repo, ["file.txt"])

    result = GitWorkspace(repo).apply_patch("")

    assert result.status is PatchStatus.CHECK_FAILED
    assert result.applied is False
    assert result.failure_reason == "Patch is empty."
    assert repository_state(repo, ["file.txt"]) == before


def test_binary_patch_is_rejected_without_modifying_repository(
    git_repo_factory: GitRepoFactory,
) -> None:
    donor = git_repo_factory({"asset.bin": b"\x00old-binary-content\xff"})
    target = git_repo_factory({"asset.bin": b"\x00old-binary-content\xff"})
    write_file(donor, "asset.bin", b"\x00new-binary-content\xfe")
    patch = make_patch(donor)
    assert "GIT binary patch" in patch
    before = repository_state(target, ["asset.bin"])

    result = GitWorkspace(target).apply_patch(patch)

    assert result.status is PatchStatus.SECURITY_REJECTED
    assert result.applied is False
    assert result.failure_reason == "Binary patches are disabled."
    assert repository_state(target, ["asset.bin"]) == before


def test_patch_size_limit_is_enforced_before_parsing(
    git_repo_factory: GitRepoFactory,
) -> None:
    repo = git_repo_factory({})
    validator = PatchValidator(repo, max_patch_bytes=32)
    oversized = "x" * 33
    before = repository_state(repo, [])

    result = validator.validate(oversized)

    assert result.status is PatchStatus.SECURITY_REJECTED
    assert result.failure_reason == "Patch exceeds size limit."
    assert repository_state(repo, []) == before


def test_patch_file_count_limit_is_enforced(
    git_repo_factory: GitRepoFactory,
) -> None:
    donor = git_repo_factory({"one.txt": "old\n", "two.txt": "old\n"})
    target = git_repo_factory({"one.txt": "old\n", "two.txt": "old\n"})
    write_file(donor, "one.txt", "new\n")
    write_file(donor, "two.txt", "new\n")
    validator = PatchValidator(target, max_files=1)
    before = repository_state(target, ["one.txt", "two.txt"])

    result = validator.validate(make_patch(donor))

    assert result.status is PatchStatus.SECURITY_REJECTED
    assert result.failure_reason == "Patch touches too many files."
    assert set(result.affected_paths) == {"one.txt", "two.txt"}
    assert repository_state(target, ["one.txt", "two.txt"]) == before


def test_apply_patch_always_calls_check_patch(
    git_repo_factory: GitRepoFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    donor = git_repo_factory({"file.txt": "old\n"})
    target = git_repo_factory({"file.txt": "old\n"})
    write_file(donor, "file.txt", "new\n")
    patch = make_patch(donor)
    workspace = GitWorkspace(target)
    original_check = workspace.check_patch
    calls: list[str] = []

    def recording_check(candidate: str):
        calls.append(candidate)
        return original_check(candidate)

    monkeypatch.setattr(workspace, "check_patch", recording_check)

    result = workspace.apply_patch(patch)

    assert result.status is PatchStatus.APPLIED
    assert calls == [patch]


@pytest.mark.parametrize("module", [workspace_module, patch_module])
def test_all_git_subprocess_calls_use_argv_without_dangerous_apply_flags(
    module: ModuleType,
) -> None:
    tree = ast.parse(inspect.getsource(module))
    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]

    assert subprocess_calls, "Expected at least one subprocess.run call."
    for call in subprocess_calls:
        assert call.args and isinstance(call.args[0], ast.List)
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        shell_value = keywords.get("shell")
        assert isinstance(shell_value, ast.Constant)
        assert shell_value.value is False
        assert "timeout" in keywords
        assert "stdout" in keywords
        assert "stderr" in keywords

    source = inspect.getsource(module)
    assert "--reject" not in source
    assert "--unsafe-paths" not in source
    assert "--unidiff-zero" not in source
