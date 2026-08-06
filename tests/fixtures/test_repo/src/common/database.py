"""Database session management."""


class AsyncSession:
    """Async database session wrapper."""

    async def execute(self, query: str) -> list:
        return []

    async def close(self) -> None:
        pass


def create_session() -> AsyncSession:
    """Create a new async database session."""
    return AsyncSession()
