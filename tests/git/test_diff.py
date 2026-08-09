from __future__ import annotations

from codeteam.git.models import GitChangeKind
from codeteam.git.workspace import GitWorkspace

from .conftest import GitRepoFactory, run_git, write_file


def test_changed_files_and_diff_include_untracked_paths_with_exact_names(
    git_repo_factory: GitRepoFactory,
) -> None:
    repo = git_repo_factory(
        {
            "src/modified.py": "value = 1\n",
            "src/rename_me.py": "unique rename content\n",
        }
    )
    write_file(repo, "src/modified.py", "value = 2\n")
    (repo / "src/rename_me.py").rename(repo / "src/renamed.py")
    run_git(repo, "add", "--all")
    write_file(repo, "new file.py", "space = True\n")
    write_file(repo, "中文文件.py", "message = '你好'\n")

    workspace = GitWorkspace(repo)
    changes = workspace.changed_files()
    by_path = {change.path: change for change in changes}

    assert by_path["src/modified.py"].kind is GitChangeKind.MODIFIED
    assert by_path["src/renamed.py"].kind is GitChangeKind.RENAMED
    assert by_path["src/renamed.py"].old_path == "src/rename_me.py"
    assert by_path["new file.py"].kind is GitChangeKind.UNTRACKED
    assert by_path["中文文件.py"].kind is GitChangeKind.UNTRACKED

    diff = workspace.diff()
    assert {change.path for change in diff.changes} == set(by_path)
    assert diff.untracked_paths == ["new file.py", "中文文件.py"]
    assert "src/modified.py" in diff.patch
    assert "new file.py" not in diff.patch
    assert "中文文件.py" not in diff.patch
    assert diff.patch_bytes == len(diff.patch.encode("utf-8"))


def test_changed_files_excludes_ignored_untracked_files(
    git_repo_factory: GitRepoFactory,
) -> None:
    repo = git_repo_factory({".gitignore": "ignored.txt\n"})
    write_file(repo, "visible.txt", "visible\n")
    write_file(repo, "ignored.txt", "ignored\n")

    paths = {change.path for change in GitWorkspace(repo).changed_files()}

    assert paths == {"visible.txt"}


def test_changed_files_reports_staged_and_unstaged_changes_against_head(
    git_repo_factory: GitRepoFactory,
) -> None:
    repo = git_repo_factory(
        {"staged.txt": "old staged\n", "unstaged.txt": "old unstaged\n"}
    )
    write_file(repo, "staged.txt", "new staged\n")
    run_git(repo, "add", "staged.txt")
    write_file(repo, "unstaged.txt", "new unstaged\n")

    changes = GitWorkspace(repo).changed_files()

    assert {(change.path, change.kind) for change in changes} == {
        ("staged.txt", GitChangeKind.MODIFIED),
        ("unstaged.txt", GitChangeKind.MODIFIED),
    }
