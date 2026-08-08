"""Authentication exceptions."""


class TokenError(Exception):
    """Base class for token-related errors."""


class InvalidRefreshTokenError(TokenError):
    """Raised when a refresh token is invalid or expired."""

    def __init__(self, message: str = "Token has expired") -> None:
        super().__init__(message)


class UserNotFoundError(TokenError):
    """Raised when the user associated with a token no longer exists."""

    def __init__(self, message: str = "User not found for token") -> None:
        super().__init__(message)


class SessionAlreadyClosedError(TokenError):
    """Raised when attempting to use an already closed database session."""

    def __init__(self, message: str = "Database session is already closed") -> None:
        super().__init__(message)


class UnsupportedTokenVersionError(TokenError):
    """Raised when the token version is not recognized by the system."""

    def __init__(self, message: str = "Unsupported token version") -> None:
        super().__init__(message)
