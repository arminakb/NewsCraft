from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

TelegramAccessMode = Literal["public_html", "mtproto_user"]
TelegramMediaKind = Literal["photo", "video", "document"]


@dataclass(frozen=True, slots=True)
class TelegramMediaReference:
    key: str
    position: int
    kind: TelegramMediaKind
    source_url: str | None
    remote_ref: str | None
    file_name: str | None
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class TelegramEnvelope:
    source_key: str
    peer_id: str
    channel_ref: str
    anchor_message_id: int
    message_ids: tuple[int, ...]
    grouped_id: str | None
    text: str
    html: str | None
    entities: tuple[dict, ...]
    published_at: datetime
    edited_at: datetime | None
    source_url: str | None
    media: tuple[TelegramMediaReference, ...] = ()


@dataclass(frozen=True, slots=True)
class TelegramFetchRequest:
    channel_ref: str
    after_id: int | None
    before_id: int | None
    limit: int
    since: datetime | None = None
    activation_boundary_at: datetime | None = None
    snapshot_token: str | None = None
    page_token: str | None = None
    api_id_secret_ref: str | None = None
    api_hash_secret_ref: str | None = None
    session_secret_ref: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramFetchResult:
    peer_id: str
    envelopes: tuple[TelegramEnvelope, ...]
    fetched_at: datetime
    snapshot_token: str
    next_page_token: str | None
    complete: bool


@dataclass(frozen=True, slots=True)
class MaterializedTelegramMedia:
    reference: TelegramMediaReference
    path: Path
    byte_length: int
    checksum_sha256: str
    mime_type: str


class TelegramSourceAdapter(Protocol):
    async def fetch(self, request: TelegramFetchRequest) -> TelegramFetchResult: ...

    async def materialize_media(
        self, envelope: TelegramEnvelope, staging_dir: Path
    ) -> tuple[MaterializedTelegramMedia, ...]: ...


def telegram_envelope_fingerprint(envelope: TelegramEnvelope) -> str:
    payload = {
        "peer_id": envelope.peer_id,
        "message_ids": list(envelope.message_ids),
        "text": envelope.text,
        "html": envelope.html,
        "entities": [_canonical_json_value(entity) for entity in envelope.entities],
        "media": [{"key": item.key, "kind": item.kind} for item in envelope.media],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_value(value):
    if isinstance(value, dict):
        return {
            str(key): _canonical_json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
