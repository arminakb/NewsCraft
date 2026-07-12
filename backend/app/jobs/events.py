from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECRET_KEY_MARKERS = (
    "authorization",
    "cookie",
    "api_key",
    "token",
    "secret",
    "password",
)


def _is_secret_like_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in _SECRET_KEY_MARKERS)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if _is_secret_like_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def redact_event_data(event_data: dict[str, Any]) -> dict[str, Any]:
    """Return a recursively sanitized copy suitable for append-only workflow events."""

    return _redact(event_data)
