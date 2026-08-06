"""Shared fixtures for repomap tests."""

from __future__ import annotations

import pytest

from codeteam.ranking.models import (
    FileSignals,
    RankedFile,
    RankingWeights,
)
from codeteam.repomap.builder import RepoMapBuilder
from codeteam.repomap.renderer import RepoMapRenderer
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
)


@pytest.fixture
def renderer() -> RepoMapRenderer:
    return RepoMapRenderer()


@pytest.fixture
def symbol_index() -> SymbolIndex:
    """Test repo symbol index."""
    si = SymbolIndex()

    # auth/service.py
    si.add(Symbol(
        name="AuthService", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/auth/service.py", line=5, column=0),
        qualified_name="AuthService",
        signature="class AuthService",
    ))
    si.add(Symbol(
        name="authenticate", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="src/auth/service.py", line=7, column=4),
        qualified_name="AuthService.authenticate",
        signature="authenticate(username: str, password: str) -> User",
    ))
    si.add(Symbol(
        name="refresh_access_token", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="src/auth/service.py", line=12, column=4),
        qualified_name="AuthService.refresh_access_token",
        signature="refresh_access_token(token: str) -> AccessToken",
    ))
    si.add(Symbol(
        name="_decode_refresh_token", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="src/auth/service.py", line=16, column=4),
        qualified_name="AuthService._decode_refresh_token",
        signature="_decode_refresh_token(token: str) -> TokenPayload",
    ))

    # auth/api.py
    si.add(Symbol(
        name="AuthController", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/auth/api.py", line=5, column=0),
        qualified_name="AuthController",
        signature="class AuthController",
    ))
    si.add(Symbol(
        name="refresh", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="src/auth/api.py", line=10, column=4),
        qualified_name="AuthController.refresh",
        signature="refresh(request: RefreshRequest) -> TokenResponse",
    ))

    # auth/exceptions.py
    si.add(Symbol(
        name="InvalidRefreshTokenError", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/auth/exceptions.py", line=7, column=0),
        qualified_name="InvalidRefreshTokenError",
        signature="class InvalidRefreshTokenError(TokenError)",
    ))

    # common/database.py
    si.add(Symbol(
        name="create_session", kind=SymbolKind.FUNCTION,
        location=SymbolLocation(file="src/common/database.py", line=12, column=0),
        qualified_name="create_session",
        signature="create_session() -> AsyncSession",
    ))

    # main.py
    si.add(Symbol(
        name="create_app", kind=SymbolKind.FUNCTION,
        location=SymbolLocation(file="src/main.py", line=3, column=0),
        qualified_name="create_app",
        signature="create_app() -> FastAPI",
    ))

    # orders/exporter.py
    si.add(Symbol(
        name="export_orders_to_csv", kind=SymbolKind.FUNCTION,
        location=SymbolLocation(file="src/orders/exporter.py", line=5, column=0),
        qualified_name="export_orders_to_csv",
        signature="export_orders_to_csv(output_path: str) -> int",
    ))

    # generated/openapi_client.py (just 1 symbol for testing)
    si.add(Symbol(
        name="GeneratedClass0001", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/generated/openapi_client.py", line=4, column=0),
        qualified_name="GeneratedClass0001",
        signature="class GeneratedClass0001",
    ))

    return si


@pytest.fixture
def ranked_auth_files() -> list[RankedFile]:
    """RankedFile list for auth query: 'refresh token error'."""
    return [
        RankedFile(
            path="src/auth/exceptions.py",
            final_score=5.0,
            rank=1,
            signals=FileSignals(symbol_match=1.0, query_match=0.0),
            matched_symbols=["InvalidRefreshTokenError"],
            is_generated=False,
            is_test=False,
        ),
        RankedFile(
            path="src/auth/service.py",
            final_score=7.5,
            rank=2,
            signals=FileSignals(symbol_match=0.8, ripgrep_match=0.6),
            matched_symbols=["refresh_access_token", "_decode_refresh_token"],
            is_generated=False,
            is_test=False,
        ),
        RankedFile(
            path="src/auth/api.py",
            final_score=5.5,
            rank=3,
            signals=FileSignals(symbol_match=0.6, import_one_hop=0.63),
            matched_symbols=["AuthController", "refresh"],
            is_generated=False,
            is_test=False,
        ),
        RankedFile(
            path="tests/test_auth.py",
            final_score=3.0,
            rank=4,
            signals=FileSignals(test_relevance=1.0),
            matched_symbols=[],
            is_generated=False,
            is_test=True,
        ),
        RankedFile(
            path="src/common/database.py",
            final_score=2.0,
            rank=5,
            signals=FileSignals(import_one_hop=0.63),
            matched_symbols=["create_session"],
            is_generated=False,
            is_test=False,
        ),
    ]


@pytest.fixture
def builder_1024(renderer: RepoMapRenderer) -> RepoMapBuilder:
    """RepoMapBuilder with 1024 token budget."""
    return RepoMapBuilder(renderer=renderer, budget_tokens=1024)


@pytest.fixture
def builder_128(renderer: RepoMapRenderer) -> RepoMapBuilder:
    """RepoMapBuilder with 128 token budget."""
    return RepoMapBuilder(renderer=renderer, budget_tokens=128)
