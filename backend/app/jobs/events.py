from __future__ import annotations

from typing import Any

from app.core.redaction import redact_secrets


def redact_event_data(event_data: dict[str, Any]) -> dict[str, Any]:
    """Return a recursively sanitized copy suitable for append-only workflow events."""

    redacted = redact_secrets(event_data)
    if not isinstance(redacted, dict):  # pragma: no cover - dict input preserves its shape
        raise TypeError("redacted event data must remain a dictionary")
    return redacted
