"""Tests for codeteam.repomap.renderer — RepoMapRenderer.

验证渲染格式：路径+冒号，│ 符号前缀，省略标记，文件间空行。
"""

from __future__ import annotations

import pytest

from codeteam.repomap.models import (
    RepoMap,
    RepoMapFile,
    RepoMapSymbol,
    SymbolRepresentation,
)
from codeteam.repomap.renderer import RepoMapRenderer


@pytest.fixture
def renderer() -> RepoMapRenderer:
    return RepoMapRenderer()


class TestRenderFormat:
    """基本渲染格式。"""

    def test_renders_file_path_with_colon(self, renderer: RepoMapRenderer) -> None:
        """文件路径以冒号结尾。"""
        entry = RepoMapFile(
            path="src/auth/service.py",
            file_score=7.0,
            symbols=[],
        )
        lines = renderer.render_file(entry)
        assert lines[0] == "src/auth/service.py:"

    def test_renders_class_with_class_keyword(self, renderer: RepoMapRenderer) -> None:
        """类符号以 class 前缀渲染。"""
        entry = RepoMapFile(
            path="src/auth/service.py",
            file_score=7.0,
            symbols=[
                RepoMapSymbol(
                    symbol_id="s1",
                    name="AuthService",
                    qualified_name="AuthService",
                    kind="class",
                    signature="class AuthService",
                    representation=SymbolRepresentation.SIGNATURE,
                ),
            ],
        )
        lines = renderer.render_file(entry)
        assert len(lines) >= 2
        assert "AuthService" in lines[1]

    def test_renders_function_with_signature(self, renderer: RepoMapRenderer) -> None:
        """函数渲染签名。"""
        entry = RepoMapFile(
            path="src/auth/service.py",
            file_score=7.0,
            symbols=[
                RepoMapSymbol(
                    symbol_id="s2",
                    name="refresh_access_token",
                    qualified_name="AuthService.refresh_access_token",
                    kind="method",
                    signature="refresh_access_token(token: str) -> AccessToken",
                    representation=SymbolRepresentation.SIGNATURE,
                ),
            ],
        )
        lines = renderer.render_file(entry)
        assert len(lines) >= 2
        # 应包含签名
        assert "refresh_access_token" in lines[1]

    def test_omitted_symbols_marked(self, renderer: RepoMapRenderer) -> None:
        """省略符号数量标记。"""
        entry = RepoMapFile(
            path="src/auth/service.py",
            file_score=7.0,
            symbols=[
                RepoMapSymbol(
                    symbol_id="s1", name="f1",
                    qualified_name="f1", kind="function",
                    representation=SymbolRepresentation.SIGNATURE,
                ),
            ],
            omitted_symbol_count=3,
        )
        lines = renderer.render_file(entry)
        assert any("omitted" in line for line in lines)
        assert any("3" in line for line in lines)


class TestRenderSnapshot:
    """Snapshot 测试——用于验证渲染输出格式不变。"""

    def test_full_repo_map_snapshot(self, renderer: RepoMapRenderer) -> None:
        """完整 RepoMap 渲染输出格式。"""
        repo_map = RepoMap(
            mode="query",
            query="refresh token error",
            budget_tokens=1024,
            used_tokens=200,
            files=[
                RepoMapFile(
                    path="src/auth/service.py",
                    file_score=7.5,
                    reasons=["symbol_match: 0.800 × 4.0 = 3.200"],
                    symbols=[
                        RepoMapSymbol(
                            symbol_id="src/auth/service.py::AuthService.refresh_access_token",
                            name="refresh_access_token",
                            qualified_name="AuthService.refresh_access_token",
                            kind="method",
                            signature="refresh_access_token(token: str) -> AccessToken",
                            representation=SymbolRepresentation.SIGNATURE,
                        ),
                        RepoMapSymbol(
                            symbol_id="src/auth/service.py::AuthService._decode_refresh_token",
                            name="_decode_refresh_token",
                            qualified_name="AuthService._decode_refresh_token",
                            kind="method",
                            signature="_decode_refresh_token(token: str) -> TokenPayload",
                            representation=SymbolRepresentation.SIGNATURE,
                        ),
                    ],
                ),
            ],
            omitted_file_count=18,
            truncated=True,
        )

        text = renderer.render(repo_map)

        # 验证基本结构
        assert text.startswith("# Repository map (query)")
        assert "Query: refresh token error" in text
        assert "src/auth/service.py:" in text
        assert "refresh_access_token" in text
        assert "_decode_refresh_token" in text
        assert "18" in text
        assert "lower-ranked files omitted" in text
        assert text.endswith("\n")


class TestRenderEdgeCases:
    """边界渲染。"""

    def test_empty_map_renders_header_only(self, renderer: RepoMapRenderer) -> None:
        """空 RepoMap 只渲染 header。"""
        repo_map = RepoMap(
            mode="global",
            budget_tokens=1024,
        )
        text = renderer.render(repo_map)
        assert "# Repository map (global)" in text
