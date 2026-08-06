"""Shared fixtures for ranking tests."""

from __future__ import annotations

import pytest

from codeteam.imports.graph import ImportGraph
from codeteam.ranking.file_ranker import FileRanker
from codeteam.ranking.models import RankingWeights, FileSignals, RankedFile
from codeteam.search.models import (
    CandidateFile,
    CandidateEvidence,
    CandidateSource,
)
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
)


@pytest.fixture
def ranking_weights() -> RankingWeights:
    """Default ranking weights."""
    return RankingWeights()


@pytest.fixture
def file_ranker(ranking_weights: RankingWeights) -> FileRanker:
    """FileRanker instance with default weights."""
    return FileRanker(weights=ranking_weights)


@pytest.fixture
def import_graph() -> ImportGraph:
    """Import graph for test repo.

    Edges:
        api.py → service.py
        api.py → exceptions.py
        service.py → database.py
        exporter.py → database.py
        worker.py → database.py
        main.py → service.py
    """
    g = ImportGraph()
    g.add_edge("src/auth/api.py", "src/auth/service.py")
    g.add_edge("src/auth/api.py", "src/auth/exceptions.py")
    g.add_edge("src/auth/service.py", "src/common/database.py")
    g.add_edge("src/orders/exporter.py", "src/common/database.py")
    g.add_edge("src/orders/worker.py", "src/common/database.py")
    g.add_edge("src/main.py", "src/auth/service.py")
    return g


@pytest.fixture
def symbol_index() -> SymbolIndex:
    """SymbolIndex with test repo symbols."""
    si = SymbolIndex()

    # auth/service.py symbols
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
        signature="authenticate(username: str, password: str) -> dict",
    ))
    si.add(Symbol(
        name="refresh_access_token", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="src/auth/service.py", line=12, column=4),
        qualified_name="AuthService.refresh_access_token",
        signature="refresh_access_token(token: str) -> dict",
    ))
    si.add(Symbol(
        name="_decode_refresh_token", kind=SymbolKind.METHOD,
        location=SymbolLocation(file="src/auth/service.py", line=16, column=4),
        qualified_name="AuthService._decode_refresh_token",
        signature="_decode_refresh_token(token: str) -> dict",
    ))

    # auth/api.py symbols
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
        signature="refresh(request: dict) -> dict",
    ))

    # auth/exceptions.py symbols
    si.add(Symbol(
        name="TokenError", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/auth/exceptions.py", line=3, column=0),
        qualified_name="TokenError",
        signature="class TokenError(Exception)",
    ))
    si.add(Symbol(
        name="InvalidRefreshTokenError", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/auth/exceptions.py", line=7, column=0),
        qualified_name="InvalidRefreshTokenError",
        signature="class InvalidRefreshTokenError(TokenError)",
    ))

    # common/database.py symbols
    si.add(Symbol(
        name="AsyncSession", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/common/database.py", line=3, column=0),
        qualified_name="AsyncSession",
        signature="class AsyncSession",
    ))
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

    # orders/worker.py
    si.add(Symbol(
        name="OrderWorker", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/orders/worker.py", line=5, column=0),
        qualified_name="OrderWorker",
        signature="class OrderWorker",
    ))

    # generated/openapi_client.py symbols (just 5 for testing)
    si.add(Symbol(
        name="GeneratedClass0001", kind=SymbolKind.CLASS,
        location=SymbolLocation(file="src/generated/openapi_client.py", line=4, column=0),
        qualified_name="GeneratedClass0001",
        signature="class GeneratedClass0001",
    ))

    return si


# ── CandidateFile builders ─────────────────────────────────

def _make_candidate(
    path: str,
    evidence_list: list[tuple[CandidateSource, str, float, int | None]] | None = None,
    is_test: bool = False,
    is_config: bool = False,
) -> CandidateFile:
    """Build a CandidateFile with evidence."""
    cf = CandidateFile(
        path=path,
        is_test=is_test,
        is_config=is_config,
    )
    if evidence_list:
        for source, query_term, weight, line_no in evidence_list:
            cf.evidence.append(
                CandidateEvidence(
                    source=source,
                    query_term=query_term,
                    detail=f"{source.value}: {query_term}",
                    line_number=line_no,
                    weight=weight,
                )
            )
            cf.preliminary_score += weight
            if source == CandidateSource.RIPGREP:
                cf.match_count += 1
    return cf


@pytest.fixture
def auth_service_candidate() -> CandidateFile:
    """Candidate: src/auth/service.py with SYMBOL_EXACT + RIPGREP evidence."""
    return _make_candidate(
        "src/auth/service.py",
        [
            (CandidateSource.SYMBOL_EXACT, "refresh_access_token", 5.0, 12),
            (CandidateSource.RIPGREP, "refresh", 2.0, 12),
            (CandidateSource.RIPGREP, "token", 2.0, 9),
        ],
    )


@pytest.fixture
def auth_api_candidate() -> CandidateFile:
    """Candidate: src/auth/api.py with SYMBOL_EXACT evidence."""
    return _make_candidate(
        "src/auth/api.py",
        [
            (CandidateSource.SYMBOL_EXACT, "AuthController", 5.0, 5),
            (CandidateSource.IMPORT_DEPENDENCY, "auth/service.py", 1.5, None),
        ],
    )


@pytest.fixture
def auth_exceptions_candidate() -> CandidateFile:
    """Candidate: src/auth/exceptions.py with SYMBOL_EXACT."""
    return _make_candidate(
        "src/auth/exceptions.py",
        [
            (CandidateSource.SYMBOL_EXACT, "InvalidRefreshTokenError", 5.0, 7),
        ],
    )


@pytest.fixture
def common_db_candidate() -> CandidateFile:
    """Candidate: src/common/database.py with IMPORT evidence only."""
    return _make_candidate(
        "src/common/database.py",
        [
            (CandidateSource.IMPORT_DEPENDENCY, "auth/service.py", 1.5, None),
            (CandidateSource.IMPORT_DEPENDENCY, "orders/exporter.py", 1.5, None),
            (CandidateSource.IMPORT_DEPENDENCY, "orders/worker.py", 1.5, None),
        ],
    )


@pytest.fixture
def generated_client_candidate() -> CandidateFile:
    """Candidate: src/generated/openapi_client.py — generated code."""
    return _make_candidate(
        "src/generated/openapi_client.py",
        [
            (CandidateSource.RIPGREP, "client", 1.0, 100),
        ],
    )


@pytest.fixture
def orders_exporter_candidate() -> CandidateFile:
    """Candidate: src/orders/exporter.py."""
    return _make_candidate(
        "src/orders/exporter.py",
        [
            (CandidateSource.SYMBOL_EXACT, "export_orders_to_csv", 5.0, 5),
            (CandidateSource.RIPGREP, "export", 2.0, 5),
            (CandidateSource.RIPGREP, "order", 2.0, 5),
        ],
    )


@pytest.fixture
def orders_worker_candidate() -> CandidateFile:
    """Candidate: src/orders/worker.py."""
    return _make_candidate(
        "src/orders/worker.py",
        [
            (CandidateSource.SYMBOL_EXACT, "OrderWorker", 5.0, 5),
            (CandidateSource.RIPGREP, "order", 2.0, 8),
        ],
    )


@pytest.fixture
def main_candidate() -> CandidateFile:
    """Candidate: src/main.py."""
    return _make_candidate(
        "src/main.py",
        [
            (CandidateSource.SYMBOL_EXACT, "create_app", 5.0, 3),
        ],
    )
