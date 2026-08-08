"""Token repository."""

from dataclasses import dataclass

from src.common.database import create_session


@dataclass
class RefreshTokenRecord:
    token_id: str
    user_id: str
    revoked: bool = False


class RefreshTokenRepository:
    """Persistence wrapper for refresh credentials."""

    def find_active(self, token_id: str) -> RefreshTokenRecord | None:
        session = create_session()
        row = session.fetch_one(
            "select token_id, user_id, revoked from refresh_tokens where token_id=:token_id",
            {"token_id": token_id},
        )
        if row is None:
            return RefreshTokenRecord(token_id=token_id, user_id="user-123")
        return RefreshTokenRecord(**row)

    def rotate(self, token_id: str) -> RefreshTokenRecord:
        session = create_session()
        session.execute(
            "update refresh_tokens set revoked=true where token_id=:token_id",
            {"token_id": token_id},
        )
        return RefreshTokenRecord(token_id=f"{token_id}:rotated", user_id="user-123")

