from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.automations.telegram.contracts import (
    MaterializedTelegramMedia,
    TelegramEnvelope,
    TelegramFetchRequest,
    TelegramFetchResult,
    TelegramMediaReference,
)
from app.sources.telegram_public import parse_public_telegram_page

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".pdf", ".doc", ".docx", ".zip"}
PUBLIC_HTML_TRANSPORT_PAGE_SIZE = 20


class PublicHtmlTelegramAdapter:
    def __init__(self, http_client: httpx.AsyncClient, *, max_media_bytes: int = 49_000_000) -> None:
        self.http_client = http_client
        self.max_media_bytes = max_media_bytes

    async def fetch(self, request: TelegramFetchRequest) -> TelegramFetchResult:
        username = _validated_username(request.channel_ref)
        page_state = _decode_token(request.page_token, "page") if request.page_token else {}
        before = page_state.get("before", request.before_id)
        params = {"before": str(before)} if before is not None else None
        response = await self.http_client.get(f"https://t.me/s/{username}", params=params)
        response.raise_for_status()

        fetched_at = datetime.now(UTC)
        parsed = parse_public_telegram_page(response.text, channel=username)
        raw_envelopes = tuple(_parsed_item_to_envelope(item, username) for item in parsed.items if item.published_at)
        snapshot_head = _snapshot_head(request.snapshot_token, raw_envelopes)
        snapshot_token = request.snapshot_token or _encode_token("snapshot", {"head": snapshot_head})
        pinned = [item for item in raw_envelopes if item.anchor_message_id <= snapshot_head]

        filtered = [item for item in pinned if _within_bounds(item, request)]
        selected = sorted(filtered, key=_envelope_coordinate, reverse=True)[: request.limit]
        selected.sort(key=_envelope_coordinate)

        has_buffered_envelopes = len(filtered) > len(selected)
        remote_exhausted = len(parsed.items) < PUBLIC_HTML_TRANSPORT_PAGE_SIZE
        boundary_proven = _boundary_proven(pinned, request)
        complete = (remote_exhausted or boundary_proven) and not has_buffered_envelopes
        next_page_token = None
        if not complete and raw_envelopes:
            cursor_envelopes = selected or pinned
            before_next = min(min(item.message_ids) for item in cursor_envelopes)
            next_page_token = _encode_token("page", {"before": before_next, "snapshot": snapshot_head})
        return TelegramFetchResult(
            peer_id=username,
            envelopes=tuple(selected),
            fetched_at=fetched_at,
            snapshot_token=snapshot_token,
            next_page_token=next_page_token,
            complete=complete,
        )

    async def materialize_media(
        self, envelope: TelegramEnvelope, staging_dir: Path
    ) -> tuple[MaterializedTelegramMedia, ...]:
        staging_dir.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        materialized: list[MaterializedTelegramMedia] = []
        try:
            for reference in envelope.media:
                if reference.source_url is None or urlsplit(reference.source_url).scheme not in {"http", "https"}:
                    raise ValueError(f"media {reference.key} has no safe public URL")
                suffix = _safe_staging_suffix(reference)
                path = staging_dir / f"{hashlib.sha256(reference.key.encode()).hexdigest()}{suffix}"
                checksum = hashlib.sha256()
                byte_length = 0
                async with self.http_client.stream("GET", reference.source_url) as response:
                    response.raise_for_status()
                    with path.open("wb") as output:
                        created.append(path)
                        async for chunk in response.aiter_bytes():
                            byte_length += len(chunk)
                            if byte_length > self.max_media_bytes:
                                raise ValueError(f"media {reference.key} exceeds {self.max_media_bytes} bytes")
                            checksum.update(chunk)
                            output.write(chunk)
                    mime_type = (
                        response.headers.get("content-type")
                        or reference.mime_type
                        or "application/octet-stream"
                    )
                    mime_type = mime_type.split(";", 1)[0].strip().lower()
                materialized.append(
                    MaterializedTelegramMedia(reference, path, byte_length, checksum.hexdigest(), mime_type)
                )
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return tuple(materialized)


def _validated_username(channel_ref: str) -> str:
    username = channel_ref[1:] if channel_ref.startswith("@") else channel_ref
    if _USERNAME_RE.fullmatch(username) is None:
        raise ValueError("channel_ref must be a Telegram username")
    return username


def _parsed_item_to_envelope(item, channel_ref: str) -> TelegramEnvelope:
    metadata = item.parser_meta
    anchor = int(metadata["message_id"])
    grouped_id = metadata.get("grouped_id")
    source_key = f"{channel_ref}:album:{grouped_id}" if grouped_id else f"{channel_ref}:message:{anchor}"
    media = tuple(
        TelegramMediaReference(
            key=f"{channel_ref}:{anchor}:{position}:{hashlib.sha256(candidate.normalized_url.encode()).hexdigest()[:16]}",
            position=position,
            kind="photo" if candidate.kind == "image" else candidate.kind,
            source_url=candidate.original_url,
            remote_ref=None,
            file_name=Path(urlsplit(candidate.normalized_url).path).name or None,
            mime_type=candidate.mime_type,
        )
        for position, candidate in enumerate(item.media_candidates)
    )
    return TelegramEnvelope(
        source_key=source_key,
        peer_id=channel_ref,
        channel_ref=channel_ref,
        anchor_message_id=anchor,
        message_ids=tuple(int(value) for value in metadata["message_ids"]),
        grouped_id=str(grouped_id) if grouped_id is not None else None,
        text=item.content_text,
        html=item.content_html,
        entities=tuple(metadata["entities"]),
        published_at=item.published_at,
        edited_at=None,
        source_url=item.source_url,
        media=media,
    )


def _within_bounds(envelope: TelegramEnvelope, request: TelegramFetchRequest) -> bool:
    if request.after_id is not None and envelope.anchor_message_id <= request.after_id:
        return False
    if request.before_id is not None and envelope.anchor_message_id >= request.before_id:
        return False
    if request.since is not None and envelope.published_at < request.since:
        return False
    if request.activation_boundary_at is not None:
        if envelope.published_at <= request.activation_boundary_at:
            return False
    return True


def _boundary_proven(envelopes: list[TelegramEnvelope], request: TelegramFetchRequest) -> bool:
    if request.activation_boundary_at is not None:
        return any(item.published_at <= request.activation_boundary_at for item in envelopes)
    if request.after_id is not None:
        return any(item.anchor_message_id <= request.after_id for item in envelopes)
    if request.since is not None:
        return any(item.published_at < request.since for item in envelopes)
    return False


def _envelope_coordinate(envelope: TelegramEnvelope) -> tuple[datetime, int]:
    return envelope.published_at, envelope.anchor_message_id


def _snapshot_head(token: str | None, envelopes: tuple[TelegramEnvelope, ...]) -> int:
    if token:
        return int(_decode_token(token, "snapshot")["head"])
    return max((item.anchor_message_id for item in envelopes), default=0)


def _encode_token(kind: str, value: dict) -> str:
    payload = json.dumps({"kind": kind, **value}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_token(token: str, expected_kind: str) -> dict:
    try:
        padded = token + "=" * (-len(token) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {expected_kind} token") from exc
    if value.get("kind") != expected_kind:
        raise ValueError(f"invalid {expected_kind} token")
    return value


def _safe_staging_suffix(reference: TelegramMediaReference) -> str:
    suffix = Path(reference.file_name or urlsplit(reference.source_url or "").path).suffix.lower()
    if suffix == ".jpeg":
        return ".jpg"
    return suffix if suffix in _MEDIA_SUFFIXES else ".bin"
