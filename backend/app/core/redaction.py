from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED = "[REDACTED]"
_SAFE_OPERATIONAL_KEYS = {
    "input_tokens",
    "max_tokens",
    "output_tokens",
    "session_count",
    "token_count",
    "token_usage",
    "tokenizer_name",
    "tokens_per_second",
}
_EXACT_SECRET_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "session",
    "session_id",
    "session_key",
    "token",
}
_AUTH_VALUE = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_TELEGRAM_BOT_TOKEN = re.compile(r"(?<!\d)\d{5,16}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])")
_URL_VALUE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_INLINE_SECRET = re.compile(
    r"(?i)\b([a-z0-9_-]*(?:api[_-]?key|password|secret|session|token)(?:_value)?)=([^\s&]+)"
)


def _normalized_key(key: object) -> str:
    return str(key).casefold().replace("-", "_").replace(" ", "_")


def _secret_key(key: object) -> bool:
    normalized = _normalized_key(key)
    if normalized in _SAFE_OPERATIONAL_KEYS:
        return False
    if normalized in _EXACT_SECRET_KEYS:
        return True
    parts = normalized.split("_")
    if any(part in {"authorization", "cookie", "credential", "password", "secret"} for part in parts):
        return True
    if "token" in parts or "session" in parts:
        return True
    return any(parts[index : index + 2] == ["api", "key"] for index in range(len(parts) - 1))


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return _REDACTED
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return url
    host = parsed.hostname
    try:
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
    except ValueError:
        return _REDACTED
    query = [
        (key, _REDACTED if _secret_key(key) else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, host, parsed.path, urlencode(query), parsed.fragment))


def _redact_string(value: str, secrets: tuple[str, ...]) -> str:
    result = value
    result = _AUTH_VALUE.sub(_REDACTED, result)
    result = _TELEGRAM_BOT_TOKEN.sub(_REDACTED, result)
    result = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}={_REDACTED}", result)
    for secret in secrets:
        if secret:
            result = result.replace(secret, _REDACTED)
    result = _URL_VALUE.sub(lambda match: redact_url(match.group(0)), result)
    return result


def _redact(value: Any, literals: tuple[str, ...], active: set[int]) -> Any:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            return _REDACTED
        active.add(identity)
        try:
            return {
                key: _REDACTED if _secret_key(key) else _redact(item, literals, active)
                for key, item in value.items()
            }
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple, set, frozenset)):
        identity = id(value)
        if identity in active:
            return _REDACTED
        active.add(identity)
        try:
            return [_redact(item, literals, active) for item in value]
        finally:
            active.remove(identity)
    if isinstance(value, str):
        return _redact_string(value, literals)
    return value


def redact_secrets(value: Any, *, secrets: Sequence[str] = ()) -> Any:
    """Return a recursively sanitized copy without changing the caller's value."""

    literals = tuple(str(secret) for secret in secrets if str(secret))
    return _redact(value, literals, set())
