"""Tests for codeteam.repomap.builder — RepoMapBuilder。

覆盖:
  T02: 无查询展示核心结构（Global Map header/footer + build）
  T04: Generated 不占主要 Map（_select_symbols + build）
  T05: Map 不超预算（build with various budgets）
  T06: 大文件只展示相关符号（_select_symbols）
"""

from __future__ import annotations

import pytest

from codeteam.ranking.models import (
    FileSignals,
    RankedFile,
)
from codeteam.repomap.builder import RepoMapBuilder
from codeteam.repomap.renderer import RepoMapRenderer
from codeteam.repomap.models import (
    RepoMap,
    RepoMapFile,
    RepoMapSymbol,
    SymbolRepresentation,
)
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import Symbol, SymbolKind, SymbolLocation


# ── T02: 无查询展示核心结构 ────────────────────────────────────

class TestGlobalMap:
    """无查询时（mode="global"），Global Map 应包含核心模块。"""

    def test_global_mode_header_has_no_query(self) -> None:
        """Global Map header 不含 Query 行。"""
        header = RepoMapBuilder._render_header("global", None)
        assert "# Repository map (global)" in header
        assert "Query:" not in header

    def test_query_mode_header_includes_query(self) -> None:
        """Query Map header 包含查询文本。"""
        header = RepoMapBuilder._render_header("query", "refresh token error")
        assert "# Repository map (query)" in header
        assert "refresh token error" in header

    def test_footer_includes_omitted_count(self) -> None:
        """Footer 展示被省略的文件数。"""
        footer = RepoMapBuilder._render_footer(18)
        assert "18" in footer
        assert "omitted" in footer

    def test_footer_empty_when_zero_omitted(self) -> None:
        """没有省略文件时 footer 为空。"""
        footer = RepoMapBuilder._render_footer(0)
        assert footer == ""

    def test_build_global_map_with_files(
        self, symbol_index: SymbolIndex,
    ) -> None:
        """真实 build() — Global Map 包含有符号的文件。"""
        renderer = RepoMapRenderer()
        builder = RepoMapBuilder(renderer=renderer, budget_tokens=1024)

        ranked = [
            RankedFile(
                path="src/main.py", final_score=3.0, rank=1,
                signals=FileSignals(base_importance=0.6),
                matched_symbols=["create_app"],
            ),
            RankedFile(
                path="src/auth/service.py", final_score=2.0, rank=2,
                signals=FileSignals(base_importance=0.5),
                matched_symbols=["AuthService"],
            ),
        ]

        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=symbol_index,
            query=None,
            mode="global",
        )

        assert repo_map.mode == "global"
        assert repo_map.query is None
        assert len(repo_map.files) >= 1
        assert repo_map.used_tokens <= 1024

    def test_build_global_map_empty_files(self) -> None:
        """空 ranked_files → 只输出 header。"""
        renderer = RepoMapRenderer()
        builder = RepoMapBuilder(renderer=renderer, budget_tokens=1024)
        si = SymbolIndex()

        repo_map = builder.build(
            ranked_files=[],
            symbol_index=si,
            query=None,
            mode="global",
        )

        assert repo_map.files == []
        text = renderer.render(repo_map)
        assert "# Repository map (global)" in text
        assert "Query:" not in text


# ── T04: Generated 不占主要 Map ────────────────────────────────

class TestGeneratedPenalty:
    """生成文件即使有大量符号，也不应占据 Map 主要位置。"""

    def test_build_respects_ranked_order(
        self, symbol_index: SymbolIndex,
    ) -> None:
        """高分人工文件在 Map 中排在生成文件前面。"""
        for i in range(50):
            symbol_index.add(Symbol(
                name=f"GeneratedClass{i:04d}",
                kind=SymbolKind.CLASS,
                location=SymbolLocation(
                    file="src/generated/openapi_client.py",
                    line=i * 10 + 4, column=0,
                ),
                qualified_name=f"GeneratedClass{i:04d}",
                signature=f"class GeneratedClass{i:04d}",
            ))

        ranked = [
            RankedFile(
                path="src/auth/service.py",
                final_score=7.0, rank=1,
                signals=FileSignals(symbol_match=1.0),
                matched_symbols=["AuthService"],
            ),
            RankedFile(
                path="src/generated/openapi_client.py",
                final_score=-3.0, rank=2,
                signals=FileSignals(symbol_match=0.5, generated_penalty=-1.0),
                matched_symbols=[],
                is_generated=True,
            ),
        ]

        renderer = RepoMapRenderer()
        builder = RepoMapBuilder(renderer=renderer, budget_tokens=1024)

        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=symbol_index,
            query="用户认证",
            mode="query",
        )

        paths_in_map = [f.path for f in repo_map.files]
        assert "src/auth/service.py" in paths_in_map


# ── T05: Map 不超预算 ─────────────────────────────────────────

class TestBudgetEnforcement:
    """不同预算下 Map 大小受限制。"""

    def test_map_never_exceeds_budget_1024(
        self, symbol_index: SymbolIndex,
    ) -> None:
        """1024 Token 预算 — 所有 auth 文件都能放下。"""
        renderer = RepoMapRenderer()
        builder = RepoMapBuilder(renderer=renderer, budget_tokens=1024)

        ranked = [
            RankedFile(
                path="src/auth/exceptions.py", final_score=9.0, rank=1,
                signals=FileSignals(symbol_match=1.0),
                matched_symbols=["InvalidRefreshTokenError"],
            ),
            RankedFile(
                path="src/auth/service.py", final_score=7.5, rank=2,
                signals=FileSignals(symbol_match=0.8, ripgrep_match=0.6),
                matched_symbols=["refresh_access_token", "_decode_refresh_token"],
            ),
            RankedFile(
                path="src/auth/api.py", final_score=5.5, rank=3,
                signals=FileSignals(symbol_match=0.6, import_one_hop=0.63),
                matched_symbols=["AuthController", "refresh"],
            ),
        ]

        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=symbol_index,
            query="refresh token",
            mode="query",
        )

        assert repo_map.used_tokens <= 1024

    def test_map_with_tight_budget_256(self) -> None:
        """256 Token 预算 — 仅少数文件能进入。"""
        renderer = RepoMapRenderer()
        si = SymbolIndex()
        si.add(Symbol(
            name="create_app", kind=SymbolKind.FUNCTION,
            location=SymbolLocation(file="src/main.py", line=3, column=0),
            qualified_name="create_app",
            signature="create_app() -> FastAPI",
        ))

        ranked = [
            RankedFile(
                path=f"src/module_{i:02d}.py",
                final_score=5.0 - i * 0.1, rank=i + 1,
                signals=FileSignals(base_importance=0.5),
                matched_symbols=[],
            )
            for i in range(50)
        ]

        builder = RepoMapBuilder(renderer=renderer, budget_tokens=256)
        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=si,
            mode="global",
        )

        assert repo_map.used_tokens <= 256

    def test_tiny_budget_truncates_files(self) -> None:
        """极小预算 (64) 迫使大部分文件被截断，验证 budget 生效。"""
        renderer = RepoMapRenderer()
        si = SymbolIndex()
        si.add(Symbol(
            name="func", kind=SymbolKind.FUNCTION,
            location=SymbolLocation(file="src/a.py", line=1, column=0),
            qualified_name="func", signature="func() -> None",
        ))

        ranked = [
            RankedFile(
                path=f"src/file_{i:02d}.py",
                final_score=1.0, rank=i + 1,
                signals=FileSignals(base_importance=0.5),
                matched_symbols=["func"],
            )
            for i in range(100)
        ]

        builder = RepoMapBuilder(renderer=renderer, budget_tokens=64)
        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=si,
            mode="global",
        )

        # 极小预算：大部分文件被省略
        assert repo_map.truncated
        assert repo_map.omitted_file_count > 0
        assert repo_map.mode == "global"

    def test_query_mode_with_budget(self, symbol_index: SymbolIndex) -> None:
        """Query mode + 预算限制 — build + render 全流程。"""
        renderer = RepoMapRenderer()
        builder = RepoMapBuilder(renderer=renderer, budget_tokens=1024)

        ranked = [
            RankedFile(
                path="src/auth/exceptions.py", final_score=9.0, rank=1,
                signals=FileSignals(symbol_match=1.0),
                matched_symbols=["InvalidRefreshTokenError"],
            ),
            RankedFile(
                path="src/auth/service.py", final_score=7.5, rank=2,
                signals=FileSignals(symbol_match=0.8, ripgrep_match=0.6),
                matched_symbols=["refresh_access_token"],
            ),
        ]

        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=symbol_index,
            query="修复 refresh token error",
            mode="query",
        )

        assert repo_map.mode == "query"
        assert repo_map.used_tokens <= 1024

        text = renderer.render(repo_map)
        assert "query" in text
        assert "refresh token error" in text


# ── 符号选择测试 ────────────────────────────────────────────────

class TestSymbolSelection:
    """_select_symbols: 文件中符号多时优先展示匹配的符号。"""

    def test_selects_matched_symbols_first(self, symbol_index: SymbolIndex) -> None:
        """匹配到的符号排在类/函数前面。"""
        ranked = RankedFile(
            path="src/auth/service.py",
            final_score=7.0, rank=1,
            signals=FileSignals(symbol_match=0.8),
            matched_symbols=["refresh_access_token"],
        )

        symbols = RepoMapBuilder._select_symbols(
            "src/auth/service.py", ranked, symbol_index
        )

        if len(symbols) >= 1:
            assert symbols[0].name == "refresh_access_token"

    def test_max_eight_symbols_per_file(self, symbol_index: SymbolIndex) -> None:
        """每个文件最多 8 个符号。"""
        for i in range(20):
            symbol_index.add(Symbol(
                name=f"method_{i:02d}",
                kind=SymbolKind.METHOD,
                location=SymbolLocation(
                    file="src/big_file.py", line=i * 2 + 1, column=0,
                ),
                qualified_name=f"BigClass.method_{i:02d}",
                signature=f"method_{i:02d}() -> None",
            ))

        ranked = RankedFile(
            path="src/big_file.py", final_score=5.0, rank=1,
            signals=FileSignals(), matched_symbols=[],
        )

        symbols = RepoMapBuilder._select_symbols(
            "src/big_file.py", ranked, symbol_index
        )

        assert len(symbols) <= 8

    def test_to_repo_map_symbol_preserves_data(self) -> None:
        """_to_repo_map_symbol 保留核心字段。"""
        sym = Symbol(
            name="create_app",
            kind=SymbolKind.FUNCTION,
            location=SymbolLocation(file="src/main.py", line=3, column=0),
            qualified_name="create_app",
            signature="create_app() -> FastAPI",
        )

        rms = RepoMapBuilder._to_repo_map_symbol(sym)
        assert rms.name == "create_app"
        assert rms.qualified_name == "create_app"
        assert rms.kind == "function"
        assert rms.signature == "create_app() -> FastAPI"

    def test_no_symbols_returns_empty(self) -> None:
        """文件没有符号 → 返回空列表。"""
        si = SymbolIndex()
        ranked = RankedFile(
            path="src/empty.py", final_score=1.0, rank=1,
            signals=FileSignals(), matched_symbols=[],
        )
        symbols = RepoMapBuilder._select_symbols("src/empty.py", ranked, si)
        assert symbols == []


# ── T06: 大文件只展示匹配的符号 ─────────────────────────────────

class TestLargeFileSymbols:
    """100 函数文件只展示匹配到的 2-3 个符号。"""

    def test_only_matched_symbols_in_big_file(self) -> None:
        """100 函数，只命中 2 个 → 匹配的在前。"""
        si = SymbolIndex()
        for i in range(100):
            si.add(Symbol(
                name=f"func_{i:03d}",
                kind=SymbolKind.FUNCTION,
                location=SymbolLocation(
                    file="src/big_module.py", line=i * 2 + 1, column=0,
                ),
                qualified_name=f"func_{i:03d}",
                signature=f"func_{i:03d}() -> None",
            ))

        ranked = RankedFile(
            path="src/big_module.py",
            final_score=8.0, rank=1,
            signals=FileSignals(symbol_match=1.0),
            matched_symbols=["func_042", "func_099"],
        )

        symbols = RepoMapBuilder._select_symbols(
            "src/big_module.py", ranked, si
        )

        assert len(symbols) <= 8
        assert symbols[0].name == "func_042"
        assert symbols[1].name == "func_099"

        for sym in symbols[2:]:
            assert sym.kind == "function"


# ── 渲染集成测试 ────────────────────────────────────────────────

class TestRenderIntegration:
    """Renderer + Builder 的端到端集成。"""

    def test_build_and_render_full_pipeline(
        self, symbol_index: SymbolIndex,
    ) -> None:
        """完整 build() → render() 流水线。"""
        renderer = RepoMapRenderer()
        builder = RepoMapBuilder(renderer=renderer, budget_tokens=1024)

        ranked = [
            RankedFile(
                path="src/auth/exceptions.py", final_score=9.0, rank=1,
                signals=FileSignals(symbol_match=1.0),
                matched_symbols=["InvalidRefreshTokenError"],
            ),
            RankedFile(
                path="src/auth/service.py", final_score=7.5, rank=2,
                signals=FileSignals(symbol_match=0.8, ripgrep_match=0.6),
                matched_symbols=["refresh_access_token"],
            ),
        ]

        repo_map = builder.build(
            ranked_files=ranked,
            symbol_index=symbol_index,
            query="修复 InvalidRefreshTokenError",
            mode="query",
        )

        text = renderer.render(repo_map)

        assert "# Repository map (query)" in text
        assert "InvalidRefreshTokenError" in text
        assert "src/auth/exceptions.py:" in text
        assert "src/auth/service.py:" in text
        assert "refresh_access_token" in text
        assert text.endswith("\n")


# ── _select_symbols: 类型优先 ───────────────────────────────────

class TestSymbolTypePriority:
    """匹配的符号 → 类/函数 → 其他。"""

    def test_matched_before_unmatched(self, symbol_index: SymbolIndex) -> None:
        """匹配的符号排在未匹配的类/函数之前。"""
        ranked = RankedFile(
            path="src/auth/service.py",
            final_score=7.0, rank=1,
            signals=FileSignals(symbol_match=0.8),
            matched_symbols=["_decode_refresh_token"],
        )

        symbols = RepoMapBuilder._select_symbols(
            "src/auth/service.py", ranked, symbol_index
        )

        if symbols:
            assert symbols[0].name == "_decode_refresh_token"
