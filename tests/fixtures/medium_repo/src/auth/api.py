"""Auth API boundary."""

from src.auth.exceptions import AuthError, RefreshTokenExpired, RefreshTokenRevoked
from src.auth.service import AuthService


class AuthController:
    """Controller for auth endpoints."""

    def __init__(self, service: AuthService | None = None) -> None:
        self.service = service or AuthService()

    def refresh(self, request: dict) -> dict:
        token = request.get("refresh_token", "")
        try:
            return {"status": 200, "body": self.service.refresh_session(token)}
        except RefreshTokenExpired as exc:
            return {"status": 401, "error": str(exc)}
        except RefreshTokenRevoked as exc:
            return {"status": 401, "error": str(exc)}
        except AuthError as exc:
            return {"status": 400, "error": str(exc)}

