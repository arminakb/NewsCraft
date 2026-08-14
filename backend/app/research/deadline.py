from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


def elapsed_ms(monotonic: Callable[[], float], started: float) -> int:
    return max(0, round((monotonic() - started) * 1_000))


async def with_deadline[T](
    awaitable: Awaitable[T],
    *,
    remaining_seconds: float,
    on_expired: Callable[[], Exception],
) -> T:
    if remaining_seconds <= 0:
        close = getattr(awaitable, "close", None)
        if close is not None:
            close()
        raise on_expired()
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining_seconds)
    except TimeoutError:
        raise on_expired() from None
