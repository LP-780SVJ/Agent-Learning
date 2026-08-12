from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from codeteam.git.models import PatchStatus
from codeteam.git.workspace import GitWorkspace

from .conftest import (
    GitRepoFactory,
    make_patch,
    repository_state,
    run_git,
    write_file,
)


def _matching_repositories(
    git_repo_factory: GitRepoFactory,
    files: Mapping[str, str | bytes],
) -> tuple[Path, Path]:
    return git_repo_factory(files), git_repo_factory(files)


def test_check_patch_does_not_modify_file_and_single_file_patch_applies(
    git_repo_factory: GitRepoFactory,
) -> None:
    donor, target = _matching_repositories(
        git_repo_factory,
        {"app.py": "answer = 41\n"},
    )
    write_file(donor, "app.py", "answer = 42\n")
    patch = make_patch(donor)
    workspace = GitWorkspace(target)
    before = repository_state(target, ["app.py"])

    validation = workspace.check_patch(patch)

    assert validation.status is PatchStatus.VALID
    assert validation.applied is False
    assert validation.affected_paths == ["app.py"]
    assert repository_state(target, ["app.py"]) == before

    result = workspace.apply_patch(patch)

    assert result.status is PatchStatus.APPLIED
    assert result.applied is True
    assert (target / "app.py").read_text(encoding="utf-8") == "answer = 42\n"


def test_multi_file_patch_applies_all_files(
    git_repo_factory: GitRepoFactory,
) -> None:
    original = {"one.txt": "one\n", "nested/two.txt": "two\n"}
    donor, target = _matching_repositories(git_repo_factory, original)
    write_file(donor, "one.txt", "ONE\n")
    write_file(donor, "nested/two.txt", "TWO\n")

    result = GitWorkspace(target).apply_patch(make_patch(donor))

    assert result.status is PatchStatus.APPLIED
    assert set(result.affected_paths) == {"one.txt", "nested/two.txt"}
    assert (target / "one.txt").read_text(encoding="utf-8") == "ONE\n"
    assert (target / "nested/two.txt").read_text(encoding="utf-8") == "TWO\n"


def test_patch_can_add_file(git_repo_factory: GitRepoFactory) -> None:
    donor, target = _matching_repositories(
        git_repo_factory,
        {"README.md": "baseline\n"},
    )
    write_file(donor, "src/new.py", "created = True\n")
    run_git(donor, "add", "--intent-to-add", "src/new.py")

    result = GitWorkspace(target).apply_patch(make_patch(donor))

    assert result.status is PatchStatus.APPLIED
    assert result.affected_paths == ["src/new.py"]
    assert (target / "src/new.py").read_text(encoding="utf-8") == (
        "created = True\n"
    )


def test_patch_can_delete_file(git_repo_factory: GitRepoFactory) -> None:
    donor, target = _matching_repositories(
        git_repo_factory,
        {"obsolete.txt": "remove me\n"},
    )
    (donor / "obsolete.txt").unlink()

    result = GitWorkspace(target).apply_patch(make_patch(donor))

    assert result.status is PatchStatus.APPLIED
    assert result.affected_paths == ["obsolete.txt"]
    assert not (target / "obsolete.txt").exists()


def test_patch_can_rename_file(git_repo_factory: GitRepoFactory) -> None:
    donor, target = _matching_repositories(
        git_repo_factory,
        {"old name.txt": "rename-only content\n"},
    )
    (donor / "old name.txt").rename(donor / "新名字.txt")
    run_git(donor, "add", "--all")
    patch = make_patch(donor)

    result = GitWorkspace(target).apply_patch(patch)

    assert result.status is PatchStatus.APPLIED
    assert result.affected_paths == ["old name.txt", "新名字.txt"]
    assert not (target / "old name.txt").exists()
    assert (target / "新名字.txt").read_text(encoding="utf-8") == (
        "rename-only content\n"
    )


def test_wrong_context_fails_without_changing_hashes_or_git_status(
    git_repo_factory: GitRepoFactory,
) -> None:
    donor, target = _matching_repositories(
        git_repo_factory,
        {"service.py": "def value():\n    return 'old'\n"},
    )
    write_file(donor, "service.py", "def value():\n    return 'new'\n")
    patch = make_patch(donor)
    write_file(target, "service.py", "def value():\n    return 'concurrent'\n")
    before = repository_state(target, ["service.py"])

    result = GitWorkspace(target).apply_patch(patch)

    assert result.status is PatchStatus.CHECK_FAILED
    assert result.applied is False
    assert repository_state(target, ["service.py"]) == before


def test_one_invalid_hunk_prevents_every_hunk_from_being_applied(
    git_repo_factory: GitRepoFactory,
) -> None:
    original_lines = [f"line {number}\n" for number in range(1, 25)]
    original = "".join(original_lines)
    donor, target = _matching_repositories(
        git_repo_factory,
        {"large.txt": original},
    )

    donor_lines = original_lines.copy()
    donor_lines[1] = "line 2 changed by patch\n"
    donor_lines[20] = "line 21 changed by patch\n"
    write_file(donor, "large.txt", "".join(donor_lines))
    patch = make_patch(donor)
    assert sum(line.startswith("@@") for line in patch.splitlines()) == 2

    target_lines = original_lines.copy()
    target_lines[20] = "line 21 changed concurrently\n"
    write_file(target, "large.txt", "".join(target_lines))
    before = repository_state(target, ["large.txt"])

    result = GitWorkspace(target).apply_patch(patch)

    assert result.status is PatchStatus.CHECK_FAILED
    assert result.applied is False
    assert repository_state(target, ["large.txt"]) == before
    assert "line 2 changed by patch" not in (target / "large.txt").read_text(
        encoding="utf-8"
    )
