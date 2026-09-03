"""Shared sanitization helpers for data crossing durable or audit boundaries."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

REDACTED = "<redacted>"

_SENSITIVE_KEY_MARKERS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
    }
)
_NON_SECRET_TOKEN_KEYS = frozenset(
    {
        "input_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "model_context_window",
        "output_tokens",
        "recent_window_budget_tokens",
        "recent_window_tokens",
        "safety_headroom_tokens",
        "tokens_after",
        "tokens_before",
        "total_input_tokens",
        "total_output_tokens",
    }
)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)\b(?:authorization\s*[:=]\s*)?bearer\s+[A-Za-z0-9._~+/=-]+"
)
_QUOTED_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|passwd|private[_ -]?key|"
    r"secret|token|credential)s?\b(\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*')"
)
_UNQUOTED_KEY_VALUE_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|passwd|private[_ -]?key|"
    r"secret|credential)s?\b([:=])([^\s,;]+)"
)
_PREFIXED_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|password|passwd|secret|credential)s?"
    r"[-_](?:value|secret|marker|key)[-_][A-Za-z0-9][A-Za-z0-9._-]{3,}\b"
)
_OPENAI_STYLE_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b")
_EXCEPTION_SENSITIVE_MARKER = re.compile(
    r"(?i)\b(?:api[_ -]?key|authorization|password|passwd|private[_ -]?key|"
    r"secret|token|credential)\b"
)
_EXCEPTION_TOKEN_VALUE_PATTERN = re.compile(
    r"(?i)\btoken([:=])([^\s,;]+)"
)


@dataclass(frozen=True)
class SafeExceptionDetails:
    """Diagnostic facts that are safe to persist for an unexpected exception."""

    code: str
    exception_type: str
    message: str
    summary_sha256: str


def is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    if normalized in _NON_SECRET_TOKEN_KEYS:
        return False
    return normalized in _SENSITIVE_KEY_MARKERS or normalized in {
        "access_token",
        "auth",
        "auth_token",
        "id_token",
        "key",
        "refresh_token",
        "session_token",
    } or normalized.endswith("_key")


def redact_sensitive_text(value: str) -> str:
    """Redact common credential forms while retaining useful diagnostics."""

    value = _AUTHORIZATION_PATTERN.sub("authorization=<redacted>", value)
    value = _QUOTED_KEY_VALUE_PATTERN.sub(r"\1\2<redacted>", value)
    value = _UNQUOTED_KEY_VALUE_PATTERN.sub(r"\1\2<redacted>", value)
    value = _OPENAI_STYLE_KEY_PATTERN.sub(REDACTED, value)
    return _PREFIXED_SECRET_PATTERN.sub(REDACTED, value)


def redact_sensitive_data(value: Any) -> Any:
    """Recursively sanitize JSON-like data without flattening its structure."""

    if isinstance(value, dict):
        return {
            key: REDACTED
            if is_sensitive_key(key)
            else redact_sensitive_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    if isinstance(value, set):
        return {redact_sensitive_data(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(redact_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def safe_exception_details(error: BaseException, *, code: str) -> SafeExceptionDetails:
    exception_type = type(error).__name__
    raw_message = f"{exception_type}: {error}"
    message = redact_sensitive_text(raw_message)
    message = _EXCEPTION_TOKEN_VALUE_PATTERN.sub(r"token\1<redacted>", message)
    if message == raw_message and _EXCEPTION_SENSITIVE_MARKER.search(raw_message):
        message = f"{exception_type}: {REDACTED}"
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return SafeExceptionDetails(
        code=code,
        exception_type=exception_type,
        message=message,
        summary_sha256=digest,
    )
