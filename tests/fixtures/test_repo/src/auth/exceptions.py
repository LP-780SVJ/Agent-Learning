"""Authentication exceptions."""


class TokenError(Exception):
    """Base class for token-related errors."""


class InvalidRefreshTokenError(TokenError):
    """Raised when a refresh token is invalid or expired."""

    def __init__(self, message: str = "Token has expired") -> None:
        super().__init__(message)
