from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.git.checkpoint import CheckpointManager, SnapshotScope
from codeteam.git.errors import (
    CheckpointOwnershipError,
    CheckpointStoreError,
    InvalidTaskIdError,
)
from codeteam.git.models import CheckpointReason, RollbackStatus

from .conftest import GitRepoFactory, repository_state, run_git, write_file


def _manager(repo: Path, tmp_path: Path, task_id: str = "task-001") -> CheckpointManager:
    return CheckpointManager(
        workspace_root=repo,
        state_root=tmp_path / "checkpoint-state",
        task_id=task_id,
    )


def _head_sha(repo: Path) -> str:
    return (
        run_git(repo, "rev-parse", "HEAD")
        .stdout.decode("utf-8", errors="replace")
        .strip()
    )


def _current_branch(repo: Path) -> str:
    return (
        run_git(repo, "branch", "--show-current")
        .stdout.decode("utf-8", errors="replace")
        .strip()
    )


def _shadow_file(manager: CheckpointManager, relative_path: str) -> Path:
    return manager.layout.shadow_repo_dir / relative_path


def test_create_checkpoint_persists_shadow_commit_and_metadata_without_workspace_git_changes(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 1\n"})
    run_git(repo, "branch", "-M", "main")
    before_head = _head_sha(repo)
    before_branch = _current_branch(repo)
    before_git_config = (repo / ".git" / "config").read_bytes()

    manager = _manager(repo, tmp_path)
    checkpoint = manager.create(CheckpointReason.TASK_START)

    assert checkpoint.checkpoint_id == "cp-000000"
    assert checkpoint.sequence == 0
    assert checkpoint.task_id == "task-001"
    assert checkpoint.reason is CheckpointReason.TASK_START
    assert checkpoint.file_count == 1
    assert checkpoint.shadow_commit_sha
    assert checkpoint.shadow_tree_sha
    assert checkpoint.workspace_head_sha == before_head
    assert (manager.layout.metadata_dir / "cp-000000.json").is_file()
    assert _shadow_file(manager, "app.py").read_text(encoding="utf-8") == "value = 1\n"
    assert _head_sha(repo) == before_head
    assert _current_branch(repo) == before_branch
    assert (repo / ".git" / "config").read_bytes() == before_git_config


def test_shadow_repo_is_outside_workspace(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 1\n"})
    manager = _manager(repo, tmp_path)

    manager.initialize()

    assert manager.layout.shadow_repo_dir.is_dir()
    assert not manager.layout.shadow_repo_dir.resolve().is_relative_to(repo.resolve())


def test_state_root_inside_workspace_is_rejected(
    git_repo_factory: GitRepoFactory,
) -> None:
    repo = git_repo_factory({"app.py": "value = 1\n"})

    with pytest.raises(ValueError, match="state_root"):
        CheckpointManager(
            workspace_root=repo,
            state_root=repo / ".codeteam" / "checkpoints",
            task_id="task-001",
        )


@pytest.mark.parametrize(
    "task_id",
    [
        pytest.param("", id="empty"),
        pytest.param("../evil", id="parent-directory"),
        pytest.param("task/001", id="forward-slash"),
        pytest.param(".hidden", id="dot-prefix"),
        pytest.param("task\\001", id="backslash"),
        pytest.param("task:001", id="unsupported-character"),
    ],
)
def test_invalid_task_id_is_rejected(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
    task_id: str,
) -> None:
    repo = git_repo_factory({"app.py": "value = 1\n"})

    with pytest.raises(InvalidTaskIdError):
        _manager(repo, tmp_path, task_id=task_id)


def test_managed_paths_use_git_tracked_and_untracked_non_ignored_scope(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory(
        {
            ".gitignore": "ignored.log\ncache/\n",
            "tracked.py": "tracked\n",
        }
    )
    write_file(repo, "untracked.py", "untracked\n")
    write_file(repo, "ignored.log", "ignored\n")
    write_file(repo, "cache/generated.py", "ignored cache\n")

    manager = _manager(repo, tmp_path)

    assert manager.managed_paths() == [".gitignore", "tracked.py", "untracked.py"]


def test_snapshot_scope_flags_are_enforced(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"tracked.py": "tracked\n"})
    write_file(repo, "untracked.py", "untracked\n")

    tracked_only = CheckpointManager(
        workspace_root=repo,
        state_root=tmp_path / "tracked-state",
        task_id="task-001",
        scope=SnapshotScope(include_untracked_non_ignored=False),
    )
    untracked_only = CheckpointManager(
        workspace_root=repo,
        state_root=tmp_path / "untracked-state",
        task_id="task-001",
        scope=SnapshotScope(include_tracked=False),
    )

    assert tracked_only.managed_paths() == ["tracked.py"]
    assert untracked_only.managed_paths() == ["untracked.py"]


def test_create_rejects_symlink_without_copying_external_target(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "baseline\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_secret = write_file(outside, "secret.txt", "do not snapshot\n")
    (repo / "leak.txt").symlink_to(outside_secret)
    run_git(repo, "add", "leak.txt")

    manager = _manager(repo, tmp_path)

    with pytest.raises(CheckpointStoreError, match="symlinks"):
        manager.create(CheckpointReason.TASK_START)

    assert outside_secret.read_text(encoding="utf-8") == "do not snapshot\n"
    assert not _shadow_file(manager, "leak.txt").exists()


def test_compare_reports_modified_added_and_deleted_without_workspace_head_change(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"a.py": "A0\n", "b.py": "B0\n"})
    manager = _manager(repo, tmp_path)
    checkpoint = manager.create(CheckpointReason.TASK_START)
    before_head = _head_sha(repo)
    write_file(repo, "a.py", "A1\n")
    (repo / "b.py").unlink()
    write_file(repo, "c.py", "C1\n")

    comparison = manager.compare(checkpoint)

    assert comparison.modified_paths == ["a.py"]
    assert comparison.added_paths == ["c.py"]
    assert comparison.deleted_paths == ["b.py"]
    assert comparison.has_changes is True
    assert _head_sha(repo) == before_head


def test_rollback_restores_tracked_modification_deletion_and_removes_untracked_addition(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"a.py": "A0\n", "b.py": "B0\n"})
    manager = _manager(repo, tmp_path)
    checkpoint = manager.create(CheckpointReason.TASK_START)
    write_file(repo, "a.py", "BROKEN\n")
    (repo / "b.py").unlink()
    write_file(repo, "c.py", "NEW\n")

    result = manager.rollback(checkpoint)

    assert result.status is RollbackStatus.SUCCESS
    assert result.target_checkpoint_id == checkpoint.checkpoint_id
    assert result.safety_checkpoint_id == "cp-000001"
    assert result.restored_paths == ["a.py", "b.py"]
    assert result.removed_paths == ["c.py"]
    assert (repo / "a.py").read_text(encoding="utf-8") == "A0\n"
    assert (repo / "b.py").read_text(encoding="utf-8") == "B0\n"
    assert not (repo / "c.py").exists()
    assert manager.compare(checkpoint).has_changes is False


def test_rollback_restores_untracked_non_ignored_file_from_checkpoint(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"tracked.py": "tracked\n"})
    write_file(repo, "scratch.py", "scratch v1\n")
    manager = _manager(repo, tmp_path)
    checkpoint = manager.create(CheckpointReason.TASK_START)
    (repo / "scratch.py").unlink()

    result = manager.rollback(checkpoint)

    assert result.status is RollbackStatus.SUCCESS
    assert (repo / "scratch.py").read_text(encoding="utf-8") == "scratch v1\n"


def test_multi_checkpoint_chain_can_restore_middle_checkpoint(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"a.py": "A0\n", "b.py": "B0\n"})
    manager = _manager(repo, tmp_path)
    cp0 = manager.create(CheckpointReason.TASK_START)
    write_file(repo, "a.py", "A1\n")
    cp1 = manager.create(CheckpointReason.AFTER_TOOL)
    write_file(repo, "b.py", "B1\n")
    cp2 = manager.create(CheckpointReason.AFTER_TOOL)
    write_file(repo, "a.py", "BROKEN\n")
    write_file(repo, "b.py", "BROKEN\n")

    result = manager.rollback(cp1)

    assert cp0.parent_checkpoint_id is None
    assert cp1.parent_checkpoint_id == cp0.checkpoint_id
    assert cp2.parent_checkpoint_id == cp1.checkpoint_id
    assert result.status is RollbackStatus.SUCCESS
    assert (repo / "a.py").read_text(encoding="utf-8") == "A1\n"
    assert (repo / "b.py").read_text(encoding="utf-8") == "B0\n"
    assert manager.compare(cp1).has_changes is False


def test_checkpoint_ownership_is_enforced(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 1\n"})
    first = _manager(repo, tmp_path, task_id="task-001")
    second = _manager(repo, tmp_path, task_id="task-002")
    checkpoint = first.create(CheckpointReason.TASK_START)

    with pytest.raises(CheckpointOwnershipError):
        second.compare(checkpoint)

    with pytest.raises(CheckpointOwnershipError):
        second.rollback(checkpoint)


def test_rollback_does_not_modify_user_git_metadata(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"app.py": "value = 1\n"})
    before_git_config = (repo / ".git" / "config").read_bytes()
    before_state = repository_state(repo, ["app.py"])
    manager = _manager(repo, tmp_path)
    checkpoint = manager.create(CheckpointReason.TASK_START)
    write_file(repo, "app.py", "value = 2\n")

    result = manager.rollback(checkpoint)

    assert result.status is RollbackStatus.SUCCESS
    assert (repo / ".git" / "config").read_bytes() == before_git_config
    assert repository_state(repo, ["app.py"]) == before_state
