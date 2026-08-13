"""One canonical JSON encoding for every persisted content hash.

Content hashes gate optimistic-concurrency responses (409s) across
generation, publishing, manual publication and exports, so every producer
of such a hash must serialise identically. Keeping a single encoder here
removes the drift risk of per-module copies of the same ``json.dumps``
keyword set.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any


def canonical_json_bytes(value: Any, *, default: Callable[[Any], Any] | None = None) -> bytes:
    """Encode ``value`` with the one serialisation every content hash uses.

    ``default`` is passed straight through to ``json.dumps``; pass ``str`` when
    the payload legitimately carries UUIDs or datetimes. Leaving it unset keeps
    the strict behaviour where a non-JSON value raises instead of silently
    hashing its ``repr``.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=default,
    ).encode("utf-8")


def sha256_canonical(value: Any, *, default: Callable[[Any], Any] | None = None) -> str:
    return hashlib.sha256(canonical_json_bytes(value, default=default)).hexdigest()
