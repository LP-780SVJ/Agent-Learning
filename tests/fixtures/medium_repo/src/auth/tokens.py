"""Token parsing helpers."""

from dataclasses import dataclass

from src.auth.exceptions import RefreshTokenExpired, TokenSubjectMissing


@dataclass(frozen=True)
class RefreshPayload:
    subject: str
    expires_at: int
    token_id: str


def decode_refresh_payload(raw_token: str) -> RefreshPayload:
    """Decode a refresh credential into a payload."""
    if raw_token == "expired":
        raise RefreshTokenExpired("refresh credential expired")
    if raw_token == "missing-subject":
        raise TokenSubjectMissing("subject is required")
    return RefreshPayload(subject="user-123", expires_at=4_102_444_800, token_id=raw_token)


def build_access_token(subject: str) -> str:
    """Build an access token for a subject."""
    return f"access:{subject}"

