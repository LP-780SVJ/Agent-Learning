"""tests/agent 共享 fixture。

遵守 .codex/AGENTS.md 测试隔离规约：
fixture 仓库一律拷贝到 tmp_path 使用，绝不直接操作 tests/fixtures/。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURE_REPO = (
    Path(__file__).resolve().parents[2]
    / "tests" / "fixtures" / "test_repo"
)


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """把 fixture 仓库拷贝到函数级 tmp_path，返回拷贝路径。

    测试只操作拷贝，原 fixture 永不触碰。
    """
    dest = tmp_path / "test_repo"
    shutil.copytree(FIXTURE_REPO, dest)
    return dest
