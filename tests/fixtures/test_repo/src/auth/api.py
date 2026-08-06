"""Authentication API controller."""

from src.auth.service import AuthService
from src.auth.exceptions import InvalidRefreshTokenError


class AuthController:
    """REST API controller for auth endpoints."""

    def __init__(self) -> None:
        self.service = AuthService()

    def refresh(self, request: dict) -> dict:
        """Handle POST /api/auth/refresh."""
        token = request.get("refresh_token", "")
        if not token:
            raise InvalidRefreshTokenError("Missing refresh token")
        return self.service.refresh_access_token(token)
