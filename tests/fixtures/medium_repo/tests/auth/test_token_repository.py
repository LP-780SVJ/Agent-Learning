"""Token repository tests."""

from src.auth.repository import RefreshTokenRepository


def test_repository_returns_record() -> None:
    record = RefreshTokenRepository().find_active("token-1")
    assert record is not None

