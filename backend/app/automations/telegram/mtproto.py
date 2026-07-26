from __future__ import annotations

import hashlib
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.automations.telegram.contracts import (
    MaterializedTelegramMedia,
    TelegramEnvelope,
    TelegramFetchRequest,
    TelegramFetchResult,
    TelegramMediaKind,
    TelegramMediaReference,
)
from app.automations.telegram.public_html import (
    _boundary_proven,
    _decode_token,
    _encode_token,
    _envelope_coordinate,
    _safe_staging_suffix,
    _within_bounds,
)
from app.core.secrets import SecretResolver


def group_mtproto_messages(
    messages: list[Any], *, peer_id: str, channel_ref: str | None = None
) -> tuple[TelegramEnvelope, ...]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    order: list[str] = []
    for message in sorted(messages, key=lambda item: int(item.id)):
        group_key = f"album:{message.grouped_id}" if message.grouped_id is not None else f"message:{message.id}"
        if group_key not in grouped:
            order.append(group_key)
        grouped[group_key].append(message)

    envelopes: list[TelegramEnvelope] = []
    for group_key in order:
        members = grouped[group_key]
        message_ids = tuple(int(item.id) for item in members)
        anchor = max(message_ids)
        grouped_id = str(members[0].grouped_id) if members[0].grouped_id is not None else None
        text = next((str(item.message) for item in members if getattr(item, "message", "")), "")
        published_at = min(item.date for item in members)
        edited_values = [item.edit_date for item in members if getattr(item, "edit_date", None) is not None]
        media_members = [item for item in members if item.media]
        media = tuple(
            _mtproto_media_reference(item, channel_ref or peer_id, position)
            for position, item in enumerate(media_members)
        )
        source_key = f"{peer_id}:album:{grouped_id}" if grouped_id else f"{peer_id}:message:{anchor}"
        envelopes.append(
            TelegramEnvelope(
                source_key=source_key,
                peer_id=peer_id,
                channel_ref=channel_ref or peer_id,
                anchor_message_id=anchor,
                message_ids=message_ids,
                grouped_id=grouped_id,
                text=text,
                html=None,
                entities=tuple(_mtproto_entities(members)),
                published_at=published_at,
                edited_at=max(edited_values) if edited_values else None,
                source_url=None,
                media=media,
            )
        )
    return tuple(sorted(envelopes, key=_envelope_coordinate))


class MtprotoTelegramAdapter:
    def __init__(
        self,
        *,
        secret_resolver: SecretResolver,
        client_factory: Callable[..., Any],
        max_media_bytes: int = 49_000_000,
        transport_page_size: int = 100,
    ) -> None:
        self.secret_resolver = secret_resolver
        self.client_factory = client_factory
        self.max_media_bytes = max_media_bytes
        self.transport_page_size = transport_page_size
        self._credential_bindings: OrderedDict[int, tuple[TelegramEnvelope, tuple[str, str, str]]] = OrderedDict()

    async def fetch(self, request: TelegramFetchRequest) -> TelegramFetchResult:
        credential_refs, credentials = self._resolve_credentials(request)
        try:
            client = self.client_factory(
                api_id=credentials[0],
                api_hash=credentials[1],
                session=credentials[2],
            )
        except Exception:
            raise RuntimeError(f"failed to initialize MTProto client for {', '.join(credential_refs)}") from None

        page_state = _decode_token(request.page_token, "page") if request.page_token else {}
        snapshot_head = None
        snapshot_token = request.snapshot_token
        if snapshot_token:
            snapshot_state = _decode_token(snapshot_token, "snapshot")
            snapshot_head = _token_integer(snapshot_state, "head", "snapshot")
        if request.page_token:
            page_snapshot_head = _token_integer(page_state, "snapshot", "page")
            if snapshot_head is not None and page_snapshot_head != snapshot_head:
                raise ValueError("page token snapshot does not match snapshot token")
            if snapshot_head is None:
                snapshot_head = page_snapshot_head
                snapshot_token = _encode_token("snapshot", {"head": snapshot_head})

        effective_max_id = request.before_id or 0
        if snapshot_head is not None:
            pinned_max_id = snapshot_head + 1
            effective_max_id = min(request.before_id, pinned_max_id) if request.before_id is not None else pinned_max_id
        offset_id = int(page_state.get("before", 0))
        offset_date = _page_offset_date(page_state)
        try:
            async with client:
                page_messages = list(
                    await client.get_messages(
                        request.channel_ref,
                        min_id=request.after_id or 0,
                        max_id=effective_max_id,
                        offset_id=offset_id,
                        offset_date=offset_date,
                        limit=self.transport_page_size,
                    )
                )
                pending_ids = [int(value) for value in page_state.get("pending_group_ids", [])]
                pending_messages = await _refetch_messages(client, request.channel_ref, pending_ids)
        except Exception:
            raise RuntimeError(f"MTProto fetch failed for channel {request.channel_ref}") from None

        fetched_at = datetime.now(UTC)
        messages = _deduplicate_messages([*pending_messages, *page_messages])
        transport_exhausted = len(page_messages) < self.transport_page_size
        held_group_id = _incomplete_oldest_group_id(page_messages, transport_exhausted=transport_exhausted)
        held_messages = [item for item in messages if str(item.grouped_id) == held_group_id]
        complete_messages = [item for item in messages if str(item.grouped_id) != held_group_id]
        raw_envelopes = group_mtproto_messages(
            complete_messages, peer_id=request.channel_ref, channel_ref=request.channel_ref
        )
        if snapshot_head is None:
            snapshot_head = max((int(item.id) for item in messages), default=0)
            snapshot_token = _encode_token("snapshot", {"head": snapshot_head})
        assert snapshot_token is not None
        pinned = [item for item in raw_envelopes if item.anchor_message_id <= snapshot_head]
        filtered = [item for item in pinned if _within_bounds(item, request)]
        selected_list = sorted(filtered, key=_envelope_coordinate, reverse=True)[: request.limit]
        selected_list.sort(key=_envelope_coordinate)
        selected = tuple(selected_list)
        has_buffered_envelopes = len(filtered) > len(selected)
        complete = (
            (transport_exhausted or _boundary_proven(pinned, request))
            and not has_buffered_envelopes
            and not held_messages
        )
        next_page_token = None
        if not complete and (page_messages or selected):
            if has_buffered_envelopes and selected:
                before_next = min(min(item.message_ids) for item in selected)
            else:
                before_next = min(int(item.id) for item in page_messages)
            next_page_token = _encode_token(
                "page",
                {
                    "before": before_next,
                    "snapshot": snapshot_head,
                    "pending_group_ids": [int(item.id) for item in held_messages],
                },
            )
        result = TelegramFetchResult(
            peer_id=request.channel_ref,
            envelopes=selected,
            fetched_at=fetched_at,
            snapshot_token=snapshot_token,
            next_page_token=next_page_token,
            complete=complete,
        )
        for envelope in result.envelopes:
            self._bind_credentials(envelope, credential_refs)
        return result

    async def materialize_media(
        self, envelope: TelegramEnvelope, staging_dir: Path
    ) -> tuple[MaterializedTelegramMedia, ...]:
        credential_refs = self._credential_refs_for(envelope)
        if credential_refs is None:
            raise RuntimeError("MTProto media materialization requires a prior fetch")
        request = TelegramFetchRequest(
            channel_ref=envelope.channel_ref,
            after_id=None,
            before_id=None,
            limit=1,
            api_id_secret_ref=credential_refs[0],
            api_hash_secret_ref=credential_refs[1],
            session_secret_ref=credential_refs[2],
        )
        _, credentials = self._resolve_credentials(request)
        try:
            client = self.client_factory(api_id=credentials[0], api_hash=credentials[1], session=credentials[2])
        except Exception:
            raise RuntimeError(f"failed to initialize MTProto media client for {', '.join(credential_refs)}") from None
        staging_dir.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        result: list[MaterializedTelegramMedia] = []
        try:
            body_error: BaseException | None = None
            try:
                await client.__aenter__()
            except Exception as exc:
                raise _MtprotoMediaClientLifecycleError("connection") from exc
            try:
                for reference in envelope.media:
                    if reference.remote_ref is None:
                        raise ValueError(f"media {reference.key} has no MTProto reference")
                    remote = _decode_token(reference.remote_ref, "mtproto_media")
                    if remote.get("channel") != envelope.channel_ref:
                        raise ValueError(f"media {reference.key} channel does not match envelope")
                    message_id = int(remote["message_id"])
                    try:
                        message = await client.get_messages(envelope.channel_ref, ids=message_id)
                    except Exception as exc:
                        raise _MtprotoMediaTransportError(reference.key) from exc
                    if isinstance(message, (list, tuple)):
                        message = message[0] if message else None
                    if message is None or int(message.id) != message_id or not message.media:
                        raise ValueError(f"media {reference.key} could not be re-fetched")
                    path = staging_dir / (
                        f"{hashlib.sha256(reference.key.encode()).hexdigest()}{_safe_staging_suffix(reference)}"
                    )
                    created.append(path)
                    checksum = hashlib.sha256()
                    byte_length = 0
                    try:
                        with path.open("wb") as output:
                            async for chunk in client.iter_download(
                                message.media,
                                request_size=min(512 * 1024, max(1, self.max_media_bytes)),
                            ):
                                if byte_length + len(chunk) > self.max_media_bytes:
                                    raise _MtprotoMediaLimitExceeded(reference.key, self.max_media_bytes)
                                output.write(chunk)
                                checksum.update(chunk)
                                byte_length += len(chunk)
                    except _MtprotoMediaLimitExceeded:
                        raise
                    except Exception as exc:
                        raise _MtprotoMediaTransportError(reference.key) from exc
                    result.append(
                        MaterializedTelegramMedia(
                            reference,
                            path,
                            byte_length,
                            checksum.hexdigest(),
                            reference.mime_type or "application/octet-stream",
                        )
                    )
            except BaseException as exc:
                body_error = exc

            try:
                suppressed = await client.__aexit__(
                    type(body_error) if body_error is not None else None,
                    body_error,
                    body_error.__traceback__ if body_error is not None else None,
                )
            except Exception as exc:
                if isinstance(body_error, (_MtprotoMediaLimitExceeded, _MtprotoMediaTransportError)):
                    raise body_error from None
                if body_error is not None and not isinstance(body_error, Exception):
                    raise body_error from None
                raise _MtprotoMediaClientLifecycleError("disconnection") from exc
            if isinstance(body_error, (_MtprotoMediaLimitExceeded, _MtprotoMediaTransportError)):
                raise body_error
            if body_error is not None and not suppressed:
                raise body_error
        except _MtprotoMediaLimitExceeded as exc:
            for path in created:
                path.unlink(missing_ok=True)
            raise ValueError(f"media {exc.media_key} exceeds {exc.limit} bytes") from None
        except _MtprotoMediaTransportError as exc:
            for path in created:
                path.unlink(missing_ok=True)
            raise RuntimeError(
                f"MTProto media materialization failed for channel {envelope.channel_ref} media {exc.media_key}"
            ) from None
        except _MtprotoMediaClientLifecycleError as exc:
            for path in created:
                path.unlink(missing_ok=True)
            raise RuntimeError(f"MTProto media client {exc.phase} failed for channel {envelope.channel_ref}") from None
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return tuple(result)

    def _bind_credentials(self, envelope: TelegramEnvelope, credential_refs: tuple[str, str, str]) -> None:
        self._credential_bindings[id(envelope)] = (envelope, credential_refs)
        self._credential_bindings.move_to_end(id(envelope))
        while len(self._credential_bindings) > 1_000:
            self._credential_bindings.popitem(last=False)

    def _credential_refs_for(self, envelope: TelegramEnvelope) -> tuple[str, str, str] | None:
        binding = self._credential_bindings.get(id(envelope))
        if binding is None or binding[0] is not envelope:
            return None
        return binding[1]

    def _resolve_credentials(self, request: TelegramFetchRequest) -> tuple[tuple[str, str, str], tuple[int, str, str]]:
        refs = (
            request.api_id_secret_ref,
            request.api_hash_secret_ref,
            request.session_secret_ref,
        )
        names = ("api_id_secret_ref", "api_hash_secret_ref", "session_secret_ref")
        for name, reference in zip(names, refs, strict=True):
            if not reference:
                raise ValueError(f"{name} is required")
        credential_refs = (str(refs[0]), str(refs[1]), str(refs[2]))
        resolved: list[str] = []
        for reference in credential_refs:
            try:
                resolved.append(self.secret_resolver.resolve(reference))
            except Exception:
                raise ValueError(f"unable to resolve Telegram credential reference {reference}") from None
        for reference, value in zip(credential_refs[1:], resolved[1:], strict=True):
            if not value.strip():
                raise ValueError(f"Telegram credential reference {reference} is empty")
        try:
            api_id = int(resolved[0].strip())
        except ValueError:
            raise ValueError(f"Telegram API ID reference {credential_refs[0]} is not a positive integer") from None
        if api_id <= 0:
            raise ValueError(f"Telegram API ID reference {credential_refs[0]} is not a positive integer")
        return credential_refs, (api_id, resolved[1], resolved[2])


def _mtproto_media_reference(message: Any, channel_ref: str, position: int) -> TelegramMediaReference:
    kind = _mtproto_media_kind(message)
    mime_type = getattr(getattr(message, "file", None), "mime_type", None)
    file_name = getattr(getattr(message, "file", None), "name", None)
    return TelegramMediaReference(
        key=f"{channel_ref}:{message.id}:{kind}",
        position=position,
        kind=kind,
        source_url=None,
        remote_ref=_encode_token("mtproto_media", {"channel": channel_ref, "message_id": int(message.id)}),
        file_name=file_name,
        mime_type=mime_type,
    )


def _mtproto_media_kind(message: Any) -> TelegramMediaKind:
    if getattr(message, "photo", None) is not None or message.media.__class__.__name__.lower().endswith("photo"):
        return "photo"
    mime_type = getattr(getattr(message, "file", None), "mime_type", "") or ""
    if getattr(message, "video", None) is not None or mime_type.startswith("video/"):
        return "video"
    return "document"


def _mtproto_entities(messages: list[Any]) -> list[dict]:
    entities: list[dict] = []
    for message in messages:
        for entity in getattr(message, "entities", None) or ():
            value = {"type": entity.__class__.__name__}
            for attribute in ("offset", "length", "url"):
                if hasattr(entity, attribute):
                    value[attribute] = getattr(entity, attribute)
            entities.append(value)
    return entities


class _MtprotoMediaTransportError(RuntimeError):
    def __init__(self, media_key: str) -> None:
        self.media_key = media_key
        super().__init__(media_key)


class _MtprotoMediaLimitExceeded(RuntimeError):
    def __init__(self, media_key: str, limit: int) -> None:
        self.media_key = media_key
        self.limit = limit
        super().__init__(media_key)


class _MtprotoMediaClientLifecycleError(RuntimeError):
    def __init__(self, phase: str) -> None:
        self.phase = phase
        super().__init__(phase)


def _page_offset_date(page_state: dict) -> datetime | None:
    value = page_state.get("offset_date")
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _token_integer(state: dict, key: str, kind: str) -> int:
    try:
        return int(state[key])
    except KeyError, TypeError, ValueError:
        raise ValueError(f"invalid {kind} token") from None


async def _refetch_messages(client: Any, channel_ref: str, message_ids: list[int]) -> list[Any]:
    if not message_ids:
        return []
    result = await client.get_messages(channel_ref, ids=message_ids)
    if result is None:
        return []
    return list(result) if isinstance(result, (list, tuple)) else [result]


def _deduplicate_messages(messages: list[Any]) -> list[Any]:
    by_id = {int(item.id): item for item in messages}
    return [by_id[message_id] for message_id in sorted(by_id, reverse=True)]


def _incomplete_oldest_group_id(messages: list[Any], *, transport_exhausted: bool) -> str | None:
    if transport_exhausted or not messages:
        return None
    oldest = min(messages, key=lambda item: int(item.id))
    return str(oldest.grouped_id) if oldest.grouped_id is not None else None
