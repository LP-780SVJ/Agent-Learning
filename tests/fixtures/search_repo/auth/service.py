"""Authentication service module."""


class UserService:
    """Manages user authentication and lifecycle."""

    def create_user(self, username: str, email: str) -> dict:
        """Create a new user account."""
        return {"id": 1, "username": username, "email": email}

    def get_user(self, user_id: int) -> dict | None:
        """Retrieve a user by ID."""
        if user_id <= 0:
            raise InvalidRefreshTokenError("User ID must be positive")
        return None


class InvalidRefreshTokenError(Exception):
    """Raised when a refresh token is invalid or expired."""

    def __init__(self, message: str = "Token has expired") -> None:
        super().__init__(message)
