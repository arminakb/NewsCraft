from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.api.article_schemas import CoverageState

ArticleSort = Literal["newest", "score"]


@dataclass(frozen=True, slots=True)
class ArticleFilters:
    search_query: str | None = None
    languages: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    source_ids: tuple[UUID, ...] = ()
    coverage: tuple[CoverageState, ...] = ()
    has_image: bool | None = None
    score_min: int | None = None
    score_max: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    collection_id: UUID | None = None

    def fingerprint(self) -> str:
        raw = json.dumps(
            asdict(self),
            default=str,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(raw).hexdigest()


_EMPTY_FILTER_KEY = ArticleFilters().fingerprint()


def encode_article_cursor(sort: ArticleSort, row: Any, filters_key: str = _EMPTY_FILTER_KEY) -> str:
    payload: dict[str, object] = {
        "v": 2,
        "sort": sort,
        "filters": filters_key,
        "display_at": row.display_at.isoformat(),
        "id": str(row.id),
    }
    if sort == "score":
        payload["score"] = row.score
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_article_cursor(
    value: str,
    sort: ArticleSort,
    filters_key: str = _EMPTY_FILTER_KEY,
) -> tuple[datetime, UUID] | tuple[int, datetime, UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
        expected_keys = {"v", "sort", "filters", "display_at", "id"}
        if sort == "score":
            expected_keys.add("score")
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError
        if payload["v"] != 2 or payload["sort"] != sort or payload["filters"] != filters_key:
            raise ValueError
        display_at = datetime.fromisoformat(payload["display_at"])
        if display_at.tzinfo is None or display_at.utcoffset() is None:
            raise ValueError
        content_item_id = UUID(payload["id"])
        if sort == "score":
            score = payload["score"]
            if isinstance(score, bool) or not isinstance(score, int):
                raise ValueError
            return score, display_at, content_item_id
        return display_at, content_item_id
    except binascii.Error, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError:
        raise ValueError("invalid article cursor") from None
