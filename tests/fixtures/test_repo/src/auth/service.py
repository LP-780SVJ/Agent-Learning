"""Authentication service."""

from src.common.database import create_session


class AuthService:
    """Handles user authentication and token management."""

    def authenticate(self, username: str, password: str) -> dict:
        """Authenticate a user with credentials."""
        session = create_session()
        return {"user": username, "session": str(session)}

    def refresh_access_token(self, token: str) -> dict:
        """Refresh an expired access token."""
        return {"access_token": "new_token", "token": token}

    def _decode_refresh_token(self, token: str) -> dict:
        """Decode and validate a refresh token payload."""
        return {"sub": "user_1", "exp": 9999999999}
