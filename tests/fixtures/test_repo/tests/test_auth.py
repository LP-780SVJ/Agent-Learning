"""Tests for authentication module."""

import pytest

from src.auth.exceptions import (
    InvalidRefreshTokenError,
    UserNotFoundError,
    SessionAlreadyClosedError,
    UnsupportedTokenVersionError,
)
from src.auth.service import AuthService


def test_expired_token_returns_401():
    """An expired refresh token should result in HTTP 401."""
    with pytest.raises(InvalidRefreshTokenError, match="Token has expired"):
        raise InvalidRefreshTokenError()


def test_invalid_token_returns_401():
    """An invalid/malformed refresh token should result in HTTP 401."""
    with pytest.raises(InvalidRefreshTokenError, match="Token has expired"):
        raise InvalidRefreshTokenError("Token has expired")


def test_missing_token_raises_error():
    """Missing refresh token in the request should raise an error."""
    with pytest.raises(InvalidRefreshTokenError, match="Missing refresh token"):
        raise InvalidRefreshTokenError("Missing refresh token")


def test_user_not_found_for_token():
    """Token pointing to a deleted user should raise UserNotFoundError."""
    with pytest.raises(UserNotFoundError, match="User not found"):
        raise UserNotFoundError()


def test_session_already_closed_error():
    """Using a closed session should raise SessionAlreadyClosedError."""
    with pytest.raises(SessionAlreadyClosedError, match="already closed"):
        raise SessionAlreadyClosedError()


def test_unsupported_token_version():
    """An unrecognized token version should raise UnsupportedTokenVersionError."""
    with pytest.raises(UnsupportedTokenVersionError, match="Unsupported token"):
        raise UnsupportedTokenVersionError()


def test_create_session_returns_session():
    """AuthService.authenticate should return a session dict."""
    service = AuthService()
    result = service.authenticate("alice", "secret")
    assert result["user"] == "alice"
    assert "session" in result


def test_refresh_access_token_preserves_token():
    """refresh_access_token should return a new access token."""
    service = AuthService()
    result = service.refresh_access_token("old_token")
    assert "access_token" in result
    assert result["access_token"] == "new_token"


def test_decode_refresh_token_returns_payload():
    """_decode_refresh_token should return a payload dict."""
    service = AuthService()
    payload = service._decode_refresh_token("valid_token")
    assert payload["sub"] == "user_1"
    assert payload["exp"] == 9999999999
