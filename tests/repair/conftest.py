"""tests/repair 共享 helper。

遵守 .codex/AGENTS.md 测试隔离规约：
Git 相关测试一律在 tmp_path 内 init 真实临时仓库 + 本地 config，
不触碰项目根与 tests/fixtures/。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def run_git(root: Path, *args: str) -> None:
    """在临时仓库内运行 git 命令（check=True，失败即抛）。"""
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        shell=False,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """函数级临时 Git 仓库（含本地 user 配置与 baseline commit）。"""
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init")
    run_git(root, "config", "user.email", "test@example.com")
    run_git(root, "config", "user.name", "Test User")
    (root / "m.py").write_text("x = 1\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "baseline")
    return root


def make_patch(old: str, new: str, filename: str = "m.py") -> str:
    """生成修改单行变量的 unified diff。"""
    return (
        f"diff --git a/{filename} b/{filename}\n"
        f"--- a/{filename}\n"
        f"+++ b/{filename}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


class ScriptedVerificationService:
    """脚本化验证服务：按顺序返回预设 VerificationResult，记录调用。

    duck typing：RepairLoop 只调用 verify(request, *, workspace_root)。
    """

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self._index = 0
        self.called_verification_ids: list[str] = []

    def verify(self, request, *, workspace_root):
        self.called_verification_ids.append(request.verification_id)
        if self._index >= len(self._results):
            raise AssertionError("ScriptedVerificationService 结果耗尽")
        result = self._results[self._index]
        self._index += 1
        return result
