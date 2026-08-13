"""Single definition of Telegram destination secret resolution.

Both the publish path and the destination-check handlers accept either a
resolver object exposing ``resolve`` or a bare callable, and both must fail
with the same permanent, non-leaking error code when the secret cannot be
produced. Keeping one copy prevents the two paths from drifting apart.
"""

from __future__ import annotations

import inspect
from typing import Any

from app.jobs.errors import PermanentJobError


async def resolve_destination_secret(resolver: Any, secret_ref: str) -> str:
    target = getattr(resolver, "resolve", None)
    if target is None and callable(resolver):
        target = resolver
    if target is None:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        )
    try:
        value = target(secret_ref)
        if inspect.isawaitable(value):
            value = await value
    except Exception:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        ) from None
    if not isinstance(value, str) or not value:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        )
    return value
