"""Database session helpers."""

from dataclasses import dataclass


@dataclass
class QueryResult:
    rows: list[dict]


class DatabaseSession:
    """Tiny fake database session used by the fixture."""

    def execute(self, query: str, params: dict | None = None) -> QueryResult:
        return QueryResult(rows=[])

    def fetch_one(self, query: str, params: dict | None = None) -> dict | None:
        return None

    def close(self) -> None:
        return None


def create_session() -> DatabaseSession:
    """Create a new database session."""
    return DatabaseSession()


def session_scope() -> DatabaseSession:
    """Return a scoped session object."""
    return create_session()

