"""Auth exceptions."""


class AuthError(Exception):
    """Base auth error."""


class RefreshTokenExpired(AuthError):
    """Raised when a refresh credential has expired."""


class RefreshTokenRevoked(AuthError):
    """Raised when a refresh credential has already been revoked."""


class TokenSubjectMissing(AuthError):
    """Raised when token payload lacks a subject."""

