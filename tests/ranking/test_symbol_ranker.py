"""Tests for codeteam.ranking.symbol_ranker — SymbolRanker。

验证文件内符号排序：查询匹配 > 类型奖励 > 可见性。
"""

from __future__ import annotations

import pytest

from codeteam.ranking.symbol_ranker import SymbolRanker
from codeteam.symbols.models import Symbol, SymbolKind, SymbolLocation


@pytest.fixture
def symbol_ranker() -> SymbolRanker:
    return SymbolRanker()


@pytest.fixture
def auth_service_symbols() -> list[Symbol]:
    """src/auth/service.py 的所有符号。"""
    return [
        Symbol(
            name="AuthService",
            kind=SymbolKind.CLASS,
            location=SymbolLocation(file="src/auth/service.py", line=5, column=0),
            qualified_name="AuthService",
            signature="class AuthService",
        ),
        Symbol(
            name="authenticate",
            kind=SymbolKind.METHOD,
            location=SymbolLocation(file="src/auth/service.py", line=7, column=4),
            qualified_name="AuthService.authenticate",
            signature="authenticate(username: str, password: str) -> dict",
        ),
        Symbol(
            name="refresh_access_token",
            kind=SymbolKind.METHOD,
            location=SymbolLocation(file="src/auth/service.py", line=12, column=4),
            qualified_name="AuthService.refresh_access_token",
            signature="refresh_access_token(token: str) -> dict",
        ),
        Symbol(
            name="_decode_refresh_token",
            kind=SymbolKind.METHOD,
            location=SymbolLocation(file="src/auth/service.py", line=16, column=4),
            qualified_name="AuthService._decode_refresh_token",
            signature="_decode_refresh_token(token: str) -> dict",
        ),
    ]


class TestSymbolRankerBasics:
    """基本排序行为。"""

    def test_ranks_exact_matched_symbols_first(
        self,
        symbol_ranker: SymbolRanker,
        auth_service_symbols: list[Symbol],
    ) -> None:
        """被精确命中的符号排在最前面。"""
        result = symbol_ranker.rank(
            auth_service_symbols,
            matched_names={"refresh_access_token"},
            query_terms=["refresh", "token"],
        )

        # refresh_access_token 应在第一位
        assert result[0][0].name == "refresh_access_token"

    def test_qualified_name_match_scores_highest(
        self,
        symbol_ranker: SymbolRanker,
    ) -> None:
        """qualified_name 精确匹配得分最高 (5.0)。"""
        syms = [
            Symbol(
                name="refresh",
                kind=SymbolKind.METHOD,
                location=SymbolLocation(file="test.py", line=1, column=0),
                qualified_name="AuthService.refresh_access_token",
                signature="refresh_access_token(token: str) -> dict",
            ),
        ]
        result = symbol_ranker.rank(
            syms,
            matched_names={"AuthService.refresh_access_token"},
        )
        assert result[0][1] >= 5.0

    def test_short_name_match_scores_4(
        self,
        symbol_ranker: SymbolRanker,
    ) -> None:
        """短名称精确匹配得分 4.0。"""
        syms = [
            Symbol(
                name="refresh_access_token",
                kind=SymbolKind.METHOD,
                location=SymbolLocation(file="test.py", line=1, column=0),
                qualified_name="AuthService.refresh_access_token",
            ),
        ]
        result = symbol_ranker.rank(
            syms,
            matched_names={"refresh_access_token"},
        )
        assert result[0][1] >= 4.0


class TestKindScore:
    """符号类型奖励。"""

    def test_class_scores_higher_than_function(
        self,
        symbol_ranker: SymbolRanker,
    ) -> None:
        """类 > 函数 > 变量。"""
        syms = [
            Symbol(
                name="my_var",
                kind=SymbolKind.VARIABLE,
                location=SymbolLocation(file="test.py", line=1, column=0),
                qualified_name="my_var",
            ),
            Symbol(
                name="my_func",
                kind=SymbolKind.FUNCTION,
                location=SymbolLocation(file="test.py", line=2, column=0),
                qualified_name="my_func",
            ),
            Symbol(
                name="MyClass",
                kind=SymbolKind.CLASS,
                location=SymbolLocation(file="test.py", line=3, column=0),
                qualified_name="MyClass",
            ),
        ]

        result = symbol_ranker.rank(syms)

        # 无查询匹配时，类应排在最前（种类得分 1.5 > 1.0 > 0）
        assert result[0][0].name == "MyClass"
        assert result[1][0].name == "my_func"
        assert result[2][0].name == "my_var"


class TestVisibilityScore:
    """可见性：公共 API > 私有实现。"""

    def test_public_symbol_above_private(
        self,
        symbol_ranker: SymbolRanker,
    ) -> None:
        """公共符号评分高于私有符号。"""
        syms = [
            Symbol(
                name="_private_method",
                kind=SymbolKind.METHOD,
                location=SymbolLocation(file="test.py", line=2, column=0),
                qualified_name="MyClass._private_method",
            ),
            Symbol(
                name="public_method",
                kind=SymbolKind.METHOD,
                location=SymbolLocation(file="test.py", line=1, column=0),
                qualified_name="MyClass.public_method",
            ),
        ]

        result = symbol_ranker.rank(syms)

        # 公有方法在前（public: +1, private: -1, 其他相同）
        assert result[0][0].name == "public_method"
        assert result[1][0].name == "_private_method"


class TestScoreOrder:
    """综合评分顺序验证。"""

    def test_query_match_beats_kind_beats_visibility(
        self,
        symbol_ranker: SymbolRanker,
    ) -> None:
        """查询匹配 (4+) > 类型奖励 (1~1.5) > 可见性 (±1)。"""
        syms = [
            # 私有变量但是被精确命中
            Symbol(
                name="_matched_var",
                kind=SymbolKind.VARIABLE,
                location=SymbolLocation(file="test.py", line=1, column=0),
                qualified_name="_matched_var",
            ),
            # 公有类但未被命中
            Symbol(
                name="UnmatchedClass",
                kind=SymbolKind.CLASS,
                location=SymbolLocation(file="test.py", line=2, column=0),
                qualified_name="UnmatchedClass",
            ),
        ]

        result = symbol_ranker.rank(
            syms,
            matched_names={"_matched_var"},
        )

        # 被命中的私有变量应排在未命中的公有类前面
        # 得分: 4.0 (exact short) + 0 (kind=var) + (-1) (private) = 3.0
        # vs: 0 (no match) + 1.5 (class) + 1.0 (public) = 2.5
        assert result[0][0].name == "_matched_var"
