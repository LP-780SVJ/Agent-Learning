from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import codeteam.git.worktree as worktree_module
from codeteam.git.errors import (
    BaseRefNotFoundError,
    BranchAlreadyExistsError,
    InvalidTaskIdError,
    WorktreePathConflictError,
)
from codeteam.git.models import WorktreeInfo
from codeteam.git.worktree import WorktreeManager

from .conftest import GitRepoFactory, repository_state, run_git, write_file


def _manager(repo: Path, tmp_path: Path) -> WorktreeManager:
    return WorktreeManager(repo_root=repo, worktree_root=tmp_path / "worktrees")


def _current_branch(repo: Path) -> str:
    return (
        run_git(repo, "branch", "--show-current")
        .stdout.decode("utf-8", errors="replace")
        .strip()
    )


def _head_sha(repo: Path) -> str:
    return (
        run_git(repo, "rev-parse", "HEAD")
        .stdout.decode("utf-8", errors="replace")
        .strip()
    )


def _branch_exists(repo: Path, branch_name: str) -> bool:
    result = run_git(
        repo,
        "show-ref",
        "--verify",
        f"refs/heads/{branch_name}",
        check=False,
    )
    return result.returncode == 0


def test_create_returns_structured_info_for_linked_worktree(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 'main'\n"})
    run_git(repo, "branch", "-M", "main")
    base_sha = _head_sha(repo)

    info = _manager(repo, tmp_path).create("task-001", base_ref="main")

    assert isinstance(info, WorktreeInfo)
    assert info.task_id == "task-001"
    assert info.branch_name == "codeteam/task-001"
    assert info.path == tmp_path / "worktrees" / "task-001"
    assert info.path.is_dir()
    assert info.base_ref == "main"
    assert info.base_sha == base_sha
    assert info.head_sha == base_sha
    assert _current_branch(info.path) == "codeteam/task-001"
    assert _head_sha(info.path) == base_sha
    assert (info.path / ".git").is_file()


def test_create_uses_specified_base_ref_for_worktree_head(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "first\n"})
    run_git(repo, "branch", "-M", "main")
    first_sha = _head_sha(repo)
    run_git(repo, "switch", "-c", "feature-base")
    write_file(repo, "app.py", "feature\n")
    run_git(repo, "add", "app.py")
    run_git(repo, "commit", "--quiet", "-m", "feature baseline")
    feature_sha = _head_sha(repo)
    run_git(repo, "switch", "main")

    info = _manager(repo, tmp_path).create(
        "task-feature",
        base_ref="feature-base",
    )

    assert feature_sha != first_sha
    assert info.base_sha == feature_sha
    assert info.head_sha == feature_sha
    assert (info.path / "app.py").read_text(encoding="utf-8") == "feature\n"


def test_task_worktree_modification_does_not_pollute_main_worktree(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 'main'\n"})
    run_git(repo, "branch", "-M", "main")
    before_main = repository_state(repo, ["app.py"])

    info = _manager(repo, tmp_path).create("task-001", base_ref="main")
    write_file(info.path, "app.py", "value = 'task-001'\n")

    assert (info.path / "app.py").read_text(encoding="utf-8") == (
        "value = 'task-001'\n"
    )
    assert (repo / "app.py").read_text(encoding="utf-8") == "value = 'main'\n"
    assert repository_state(repo, ["app.py"]) == before_main


def test_task_worktree_modification_does_not_pollute_other_task_worktree(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 'baseline'\n"})
    run_git(repo, "branch", "-M", "main")

    manager = _manager(repo, tmp_path)
    first = manager.create("task-001", base_ref="main")
    second = manager.create("task-002", base_ref="main")
    before_second = repository_state(second.path, ["app.py"])

    write_file(first.path, "app.py", "value = 'task-001'\n")

    assert (first.path / "app.py").read_text(encoding="utf-8") == (
        "value = 'task-001'\n"
    )
    assert (second.path / "app.py").read_text(encoding="utf-8") == (
        "value = 'baseline'\n"
    )
    assert (repo / "app.py").read_text(encoding="utf-8") == (
        "value = 'baseline'\n"
    )
    assert repository_state(second.path, ["app.py"]) == before_second


def test_two_task_ids_create_distinct_branches_and_paths(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    run_git(repo, "branch", "-M", "main")
    manager = _manager(repo, tmp_path)

    first = manager.create("task-001", base_ref="main")
    second = manager.create("task-002", base_ref="main")

    assert first.branch_name == "codeteam/task-001"
    assert second.branch_name == "codeteam/task-002"
    assert first.branch_name != second.branch_name
    assert first.path != second.path
    assert first.path.is_dir()
    assert second.path.is_dir()


def test_repeated_task_id_is_rejected_without_partial_state(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    run_git(repo, "branch", "-M", "main")
    manager = _manager(repo, tmp_path)
    first = manager.create("task-001", base_ref="main")
    before = repository_state(repo, ["app.py"])

    with pytest.raises(BranchAlreadyExistsError):
        manager.create("task-001", base_ref="main")

    assert repository_state(repo, ["app.py"]) == before
    assert _branch_exists(repo, "codeteam/task-001")
    assert first.path.is_dir()


def test_existing_task_branch_is_rejected_without_creating_path(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    run_git(repo, "branch", "-M", "main")
    run_git(repo, "branch", "codeteam/task-001")
    before = repository_state(repo, ["app.py"])

    with pytest.raises(BranchAlreadyExistsError):
        _manager(repo, tmp_path).create("task-001", base_ref="main")

    assert repository_state(repo, ["app.py"]) == before
    assert not (tmp_path / "worktrees" / "task-001").exists()


@pytest.mark.parametrize(
    "task_id",
    [
        pytest.param("", id="empty"),
        pytest.param("../evil", id="parent-directory"),
        pytest.param("task/001", id="forward-slash"),
        pytest.param(".hidden", id="dot-prefix"),
        pytest.param("task\\001", id="backslash"),
    ],
)
def test_invalid_task_id_is_rejected_without_branch_or_path_escape(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
    task_id: str,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    run_git(repo, "branch", "-M", "main")
    before = repository_state(repo, ["app.py"])
    outside = tmp_path / "evil"

    with pytest.raises(InvalidTaskIdError):
        _manager(repo, tmp_path).create(task_id, base_ref="main")

    assert repository_state(repo, ["app.py"]) == before
    assert not _branch_exists(repo, "codeteam/evil")
    assert not _branch_exists(repo, f"codeteam/{task_id}")
    assert not outside.exists()


def test_existing_worktree_path_is_rejected_without_overwriting_contents(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    run_git(repo, "branch", "-M", "main")
    existing_path = tmp_path / "worktrees" / "task-001"
    existing_path.mkdir(parents=True)
    marker = write_file(existing_path, "marker.txt", "keep me\n")
    before = repository_state(repo, ["app.py"])

    with pytest.raises(WorktreePathConflictError):
        _manager(repo, tmp_path).create("task-001", base_ref="main")

    assert repository_state(repo, ["app.py"]) == before
    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert not _branch_exists(repo, "codeteam/task-001")


def test_missing_base_ref_fails_clearly_without_partial_state(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    run_git(repo, "branch", "-M", "main")
    before = repository_state(repo, ["app.py"])

    with pytest.raises(BaseRefNotFoundError, match="Base ref"):
        _manager(repo, tmp_path).create("task-001", base_ref="missing-ref")

    assert repository_state(repo, ["app.py"]) == before
    assert not _branch_exists(repo, "codeteam/task-001")
    assert not (tmp_path / "worktrees" / "task-001").exists()


def test_worktree_subprocess_calls_use_safe_argv_and_no_force_flags() -> None:
    tree = ast.parse(inspect.getsource(worktree_module))
    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]

    assert subprocess_calls, "Expected WorktreeManager to call subprocess.run."
    for call in subprocess_calls:
        assert call.args and isinstance(call.args[0], ast.List)
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        shell_value = keywords.get("shell")
        assert isinstance(shell_value, ast.Constant)
        assert shell_value.value is False
        assert "timeout" in keywords
        assert "stdout" in keywords
        assert "stderr" in keywords

    source = inspect.getsource(worktree_module)
    assert "--force" not in source
    assert '"-B"' not in source
    assert "'-B'" not in source
