from __future__ import annotations

from pathlib import Path

from codeteam.git.worktree_paths import (
    eval_worktree_root,
    repository_worktree_root,
    resolve_worktree_root,
)


def test_worktree_root_precedence(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    explicit = tmp_path / "explicit"

    assert resolve_worktree_root(explicit, environ={}) == explicit
    assert resolve_worktree_root(
        environ={"CODETEAM_WORKTREE_ROOT": str(configured)}
    ) == configured


def test_default_worktree_root_uses_current_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert resolve_worktree_root(environ={}) == tmp_path / ".codeteam" / "worktrees"


def test_repository_worktree_roots_are_stable_and_collision_resistant(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one" / "repo"
    second = tmp_path / "two" / "repo"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    base = tmp_path / "worktrees"

    first_root = repository_worktree_root(first, worktree_root=base)
    repeated = repository_worktree_root(first, worktree_root=base)
    second_root = repository_worktree_root(second, worktree_root=base)

    assert first_root == repeated
    assert first_root.parent == base / "repos"
    assert first_root.name.startswith("repo-")
    assert first_root != second_root


def test_eval_worktree_root_is_namespaced_by_run_id(tmp_path: Path) -> None:
    root = eval_worktree_root("baseline-abc123", worktree_root=tmp_path)

    assert root == tmp_path / "evals" / "baseline-abc123"
