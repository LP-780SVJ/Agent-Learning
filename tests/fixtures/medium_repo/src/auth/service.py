"""Auth business logic."""

from src.auth.exceptions import RefreshTokenRevoked
from src.auth.repository import RefreshTokenRepository
from src.auth.tokens import build_access_token, decode_refresh_payload


class AuthService:
    """Coordinates token validation, repository state, and rotation."""

    def __init__(self, repository: RefreshTokenRepository | None = None) -> None:
        self.repository = repository or RefreshTokenRepository()

    def refresh_session(self, raw_refresh_token: str) -> dict:
        """Refresh a login session."""
        payload = decode_refresh_payload(raw_refresh_token)
        record = self.repository.find_active(payload.token_id)
        if record is None or record.revoked:
            raise RefreshTokenRevoked("refresh credential revoked")
        rotated = self.repository.rotate(payload.token_id)
        return {
            "access_token": build_access_token(payload.subject),
            "refresh_token": rotated.token_id,
        }

    def revoke_session(self, raw_refresh_token: str) -> None:
        payload = decode_refresh_payload(raw_refresh_token)
        self.repository.rotate(payload.token_id)

