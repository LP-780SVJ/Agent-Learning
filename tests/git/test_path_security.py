from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.git.errors import PatchSecurityError
from codeteam.git.models import PatchStatus
from codeteam.git.patch import PatchValidator, validate_patch_path
from codeteam.git.workspace import GitWorkspace

from .conftest import GitRepoFactory, repository_state


def _new_file_patch(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        "+written by patch\n"
    )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../../outside.txt",
        "/tmp/absolute.txt",
        r"C:\\Users\\User\\absolute.txt",
        ".git/config",
        ".GIT/config",
    ],
)
def test_path_validator_rejects_escape_absolute_and_git_metadata_paths(
    git_repo_factory: GitRepoFactory,
    unsafe_path: str,
) -> None:
    repo = git_repo_factory({})

    with pytest.raises(PatchSecurityError):
        validate_patch_path(repo, unsafe_path)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../../outside.txt",
        "/tmp/absolute.txt",
        r"C:\\Users\\User\\absolute.txt",
        ".git/config",
    ],
)
def test_patch_validator_classifies_unsafe_patch_as_security_rejected(
    git_repo_factory: GitRepoFactory,
    unsafe_path: str,
) -> None:
    repo = git_repo_factory({})
    before = repository_state(repo, [])

    result = PatchValidator(repo).validate(_new_file_patch(unsafe_path))

    assert result.status is PatchStatus.SECURITY_REJECTED
    assert result.applied is False
    assert unsafe_path in result.affected_paths
    assert repository_state(repo, []) == before
    if unsafe_path == "../../outside.txt":
        assert not (repo.parent.parent / "outside.txt").exists()


def test_symlink_escape_is_rejected_and_outside_file_is_unchanged(
    git_repo_factory: GitRepoFactory,
    tmp_path: Path,
) -> None:
    repo = git_repo_factory({"README.md": "baseline\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "escaped.txt"
    outside_file.write_text("outside baseline\n", encoding="utf-8")
    (repo / "link").symlink_to(outside, target_is_directory=True)
    patch = _new_file_patch("link/escaped.txt")
    before_repo = repository_state(repo, ["README.md"])
    before_outside = outside_file.read_bytes()

    result = GitWorkspace(repo).apply_patch(patch)

    assert result.status is PatchStatus.SECURITY_REJECTED
    assert result.applied is False
    assert repository_state(repo, ["README.md"]) == before_repo
    assert outside_file.read_bytes() == before_outside
