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
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
