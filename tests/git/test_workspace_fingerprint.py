import subprocess
from pathlib import Path

from codeteam.git.workspace import GitWorkspace


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        shell=False,
        timeout=10,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Fingerprint Test")
    _git(repo, "config", "user.email", "fingerprint@example.com")
    (repo / "tracked.txt").write_text("version one\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "baseline")
    return repo


def test_workspace_fingerprint_detects_same_path_content_change(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    workspace = GitWorkspace(repo)
    before, before_entries = workspace.content_fingerprint()

    (repo / "tracked.txt").write_text("version two\n", encoding="utf-8")
    after, after_entries = workspace.content_fingerprint()

    assert before != after
    assert dict(before_entries)["tracked.txt"] != dict(after_entries)["tracked.txt"]


def test_workspace_fingerprint_does_not_follow_symlink_target(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret one\n", encoding="utf-8")
    (repo / "outside-link").symlink_to(outside)
    workspace = GitWorkspace(repo)
    before, before_entries = workspace.content_fingerprint()

    outside.write_text("secret two\n", encoding="utf-8")
    after, after_entries = workspace.content_fingerprint()

    assert before == after
    assert before_entries == after_entries
