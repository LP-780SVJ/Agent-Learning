"""Shared fixtures for search module tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.imports.graph import ImportGraph
from codeteam.repository.filename_index import FilenameIndex
from codeteam.repository.models import (
    FileKind,
    RepositoryFile,
    RepositorySnapshot,
)
from codeteam.search.candidate_generator import CandidateGenerator
from codeteam.search.query_analyzer import QueryAnalyzer
from codeteam.search.ripgrep import RipgrepClient
from codeteam.symbols.index import SymbolIndex
from codeteam.symbols.models import (
    Symbol,
    SymbolKind,
    SymbolLocation,
)


@pytest.fixture
def search_repo(tmp_path: Path) -> Path:
    """路径到搜索fixture仓库。"""
    return tmp_path


@pytest.fixture
def query_analyzer() -> QueryAnalyzer:
    """QueryAnalyzer 实例。"""
    return QueryAnalyzer()


@pytest.fixture
def ripgrep_client() -> RipgrepClient:
    """RipgrepClient 实例。"""
    return RipgrepClient(timeout_seconds=10.0)


@pytest.fixture
def filename_index() -> FilenameIndex:
    """预填充的 FilenameIndex。"""
    fi = FilenameIndex()
    paths = [
        "auth/service.py",
        "auth/repository.py",
        "errors.py",
        "中文注释.py",
        "README.md",
    ]
    fi.add_batch(paths)
    return fi


@pytest.fixture
def symbol_index() -> SymbolIndex:
    """预填充的 SymbolIndex，包含已知测试符号。"""
    si = SymbolIndex()

    # UserService in auth/service.py
    si.add(
        Symbol(
            name="UserService",
            kind=SymbolKind.CLASS,
            location=SymbolLocation(file="auth/service.py", line=3, column=0),
            qualified_name="UserService",
            signature="",
        )
    )
    # InvalidRefreshTokenError in auth/service.py
    si.add(
        Symbol(
            name="InvalidRefreshTokenError",
            kind=SymbolKind.CLASS,
            location=SymbolLocation(file="auth/service.py", line=17, column=0),
            qualified_name="InvalidRefreshTokenError",
            signature="",
        )
    )
    # UserRepository in auth/repository.py
    si.add(
        Symbol(
            name="UserRepository",
            kind=SymbolKind.CLASS,
            location=SymbolLocation(file="auth/repository.py", line=3, column=0),
            qualified_name="UserRepository",
            signature="",
        )
    )
    # ServiceError in errors.py
    si.add(
        Symbol(
            name="ServiceError",
            kind=SymbolKind.CLASS,
            location=SymbolLocation(file="errors.py", line=3, column=0),
            qualified_name="ServiceError",
            signature="",
        )
    )
    # TIMEOUT_ERROR in errors.py
    si.add(
        Symbol(
            name="TIMEOUT_ERROR",
            kind=SymbolKind.VARIABLE,
            location=SymbolLocation(file="errors.py", line=10, column=0),
            qualified_name="TIMEOUT_ERROR",
            signature="",
        )
    )
    # DatabaseError in errors.py
    si.add(
        Symbol(
            name="DatabaseError",
            kind=SymbolKind.CLASS,
            location=SymbolLocation(file="errors.py", line=13, column=0),
            qualified_name="DatabaseError",
            signature="",
        )
    )
    return si


@pytest.fixture
def import_graph() -> ImportGraph:
    """预填充的 ImportGraph。"""
    ig = ImportGraph()
    # api.py -> service.py
    ig.add_edge("auth/api.py", "auth/service.py")
    # service.py -> repository.py
    ig.add_edge("auth/service.py", "auth/repository.py")
    # service.py -> errors.py
    ig.add_edge("auth/service.py", "errors.py")
    # api.py -> errors.py
    ig.add_edge("auth/api.py", "errors.py")
    return ig


@pytest.fixture
def repository_snapshot() -> RepositorySnapshot:
    """预填充的 RepositorySnapshot。"""
    root = Path("/fake/repo")
    files = [
        RepositoryFile(
            path="auth/service.py",
            language="python",
            kind=FileKind.SOURCE,
            size_bytes=500,
        ),
        RepositoryFile(
            path="auth/repository.py",
            language="python",
            kind=FileKind.SOURCE,
            size_bytes=300,
        ),
        RepositoryFile(
            path="errors.py",
            language="python",
            kind=FileKind.SOURCE,
            size_bytes=200,
        ),
        RepositoryFile(
            path="中文注释.py",
            language="python",
            kind=FileKind.SOURCE,
            size_bytes=150,
        ),
        RepositoryFile(
            path="README.md",
            language="markdown",
            kind=FileKind.DOCUMENTATION,
            size_bytes=100,
        ),
    ]
    return RepositorySnapshot(
        root=root,
        files=files,
        is_git_repo=True,
        languages={"python": 4, "markdown": 1},
    )


@pytest.fixture
def candidate_generator(
    query_analyzer: QueryAnalyzer,
    ripgrep_client: RipgrepClient,
    symbol_index: SymbolIndex,
    filename_index: FilenameIndex,
    import_graph: ImportGraph,
    repository_snapshot: RepositorySnapshot,
) -> CandidateGenerator:
    """CandidateGenerator 实例，注入所有依赖。"""
    return CandidateGenerator(
        analyzer=query_analyzer,
        ripgrep=ripgrep_client,
        symbol_index=symbol_index,
        filename_index=filename_index,
        import_graph=import_graph,
        repository=repository_snapshot,
    )
