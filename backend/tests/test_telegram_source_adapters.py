from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.automations.telegram.acceptance_fixture import TelegramAcceptanceFixtureTransport
from app.automations.telegram.contracts import (
    TelegramEnvelope,
    TelegramFetchRequest,
    TelegramFetchResult,
    TelegramMediaReference,
    telegram_envelope_fingerprint,
)
from app.automations.telegram.mtproto import MtprotoTelegramAdapter, group_mtproto_messages
from app.automations.telegram.public_html import PublicHtmlTelegramAdapter, _encode_token
from app.automations.telegram.registry import TelegramSourceRegistry


def _request(**overrides) -> TelegramFetchRequest:
    values = {
        "channel_ref": "example_channel",
        "after_id": None,
        "before_id": None,
        "limit": 20,
    }
    values.update(overrides)
    return TelegramFetchRequest(**values)


def _envelope(**overrides) -> TelegramEnvelope:
    values = {
        "source_key": "example_channel:41",
        "peer_id": "example_channel",
        "channel_ref": "example_channel",
        "anchor_message_id": 41,
        "message_ids": (41,),
        "grouped_id": None,
        "text": "body",
        "html": "<b>body</b>",
        "entities": ({"type": "bold", "text": "body"},),
        "published_at": datetime(2026, 7, 11, 8, 1, tzinfo=UTC),
        "edited_at": None,
        "source_url": "https://t.me/example_channel/41",
        "media": (),
    }
    values.update(overrides)
    return TelegramEnvelope(**values)


def test_transport_contracts_have_exact_fields_and_are_frozen():
    assert [field.name for field in fields(TelegramMediaReference)] == [
        "key", "position", "kind", "source_url", "remote_ref", "file_name", "mime_type"
    ]
    assert [field.name for field in fields(TelegramFetchResult)] == [
        "peer_id", "envelopes", "fetched_at", "snapshot_token", "next_page_token", "complete"
    ]
    envelope = _envelope()
    with pytest.raises(FrozenInstanceError):
        envelope.text = "changed"


def test_envelope_fingerprint_tracks_content_entities_and_media_but_not_fetch_metadata():
    media = TelegramMediaReference("photo:1", 0, "photo", "https://cdn.example/1.jpg", None, None, None)
    original = _envelope(media=(media,))
    metadata_only = _envelope(media=(media,), edited_at=datetime(2026, 7, 12, tzinfo=UTC))

    assert telegram_envelope_fingerprint(original) == telegram_envelope_fingerprint(metadata_only)
    assert telegram_envelope_fingerprint(original) != telegram_envelope_fingerprint(
        _envelope(text="changed", media=(media,))
    )
    assert telegram_envelope_fingerprint(original) != telegram_envelope_fingerprint(
        _envelope(entities=({"type": "link", "url": "https://example.com"},), media=(media,))
    )
    assert telegram_envelope_fingerprint(original) != telegram_envelope_fingerprint(
        _envelope(media=(TelegramMediaReference("photo:2", 0, "photo", None, None, None, None),))
    )


async def test_public_html_adapter_returns_ordered_album_and_respects_after_id():
    html = Path("tests/fixtures/telegram_public_album.html").read_text(encoding="utf-8")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html)))
    adapter = PublicHtmlTelegramAdapter(client)

    result = await adapter.fetch(_request(after_id=40))

    assert [envelope.anchor_message_id for envelope in result.envelopes] == [41, 44]
    assert result.envelopes[1].message_ids == (42, 43, 44)
    assert [media.position for media in result.envelopes[1].media] == [0, 1, 2]
    assert [media.kind for media in result.envelopes[1].media] == ["photo", "video", "document"]
    assert result.snapshot_token
    assert result.complete is True
    await client.aclose()


async def test_test_only_acceptance_transport_serves_album_and_materializes_media(tmp_path):
    transport = TelegramAcceptanceFixtureTransport(Path("tests/fixtures/telegram_public_album.html"))
    client = httpx.AsyncClient(transport=transport)
    adapter = PublicHtmlTelegramAdapter(client)

    result = await adapter.fetch(_request(after_id=41))
    assert [item.message_ids for item in result.envelopes] == [(42, 43, 44)]

    materialized = await adapter.materialize_media(result.envelopes[0], tmp_path)
    assert [item.reference.kind for item in materialized] == ["photo", "video", "document"]
    assert all(item.path.read_bytes() for item in materialized)
    assert all(len(item.checksum_sha256) == 64 for item in materialized)
    await client.aclose()


async def test_public_html_adapter_applies_exclusive_bounds_and_since():
    html = Path("tests/fixtures/telegram_public_album.html").read_text(encoding="utf-8")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html)))
    adapter = PublicHtmlTelegramAdapter(client)

    bounded = await adapter.fetch(
        _request(
            after_id=41,
            before_id=45,
            since=datetime(2026, 7, 11, 8, 2, tzinfo=UTC),
        )
    )

    assert [envelope.anchor_message_id for envelope in bounded.envelopes] == [44]
    await client.aclose()


async def test_public_html_activation_excludes_messages_at_the_exact_boundary():
    html = _public_page(42, 41)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html)))
    adapter = PublicHtmlTelegramAdapter(client)

    result = await adapter.fetch(
        _request(limit=20, activation_boundary_at=datetime(2026, 7, 11, 8, 42, tzinfo=UTC))
    )

    assert result.envelopes == ()
    assert result.complete is True
    await client.aclose()


async def test_public_html_adapter_pages_from_oldest_selected_envelope_without_skipping_buffered_rows():
    pages = [
        _public_page(50, 49, 48),
        _public_page(48),
    ]
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=pages.pop(0))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    adapter = PublicHtmlTelegramAdapter(client)

    first = await adapter.fetch(_request(limit=2))
    second = await adapter.fetch(
        _request(limit=2, snapshot_token=first.snapshot_token, page_token=first.next_page_token)
    )

    assert [item.anchor_message_id for item in first.envelopes] == [49, 50]
    assert first.complete is False
    assert first.next_page_token is not None
    assert [item.anchor_message_id for item in second.envelopes] == [48]
    assert second.snapshot_token == first.snapshot_token
    assert second.complete is True
    assert requests[1].url.params["before"] == "49"
    await client.aclose()


async def test_public_html_completion_uses_transport_page_size_not_large_caller_limit():
    html = _public_page(*range(40, 60))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html)))

    result = await PublicHtmlTelegramAdapter(client).fetch(_request(limit=100))

    assert len(result.envelopes) == 20
    assert result.complete is False
    assert result.next_page_token is not None
    await client.aclose()


async def test_public_html_adapter_applies_limit_after_complete_album_grouping():
    html = Path("tests/fixtures/telegram_public_album.html").read_text(encoding="utf-8")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html)))

    result = await PublicHtmlTelegramAdapter(client).fetch(_request(limit=1))

    assert [item.anchor_message_id for item in result.envelopes] == [44]
    assert result.envelopes[0].message_ids == (42, 43, 44)
    assert len(result.envelopes[0].media) == 3
    await client.aclose()


async def test_public_html_adapter_materializes_media_with_limit_and_cleans_partial_file(tmp_path):
    media = TelegramMediaReference(
        "photo:1", 0, "photo", "https://cdn.example/photo.jpg", None, "../../photo.jpg", "image/jpeg"
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"12345")
        )
    )
    adapter = PublicHtmlTelegramAdapter(client, max_media_bytes=4)

    with pytest.raises(ValueError, match="exceeds 4 bytes"):
        await adapter.materialize_media(_envelope(media=(media,)), tmp_path)

    assert list(tmp_path.iterdir()) == []
    await client.aclose()


@pytest.mark.parametrize("channel_ref", ["https://t.me/example", "bad/channel", "bad?before=1", "../escape"])
async def test_public_html_adapter_rejects_unsafe_channel_references(channel_ref):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    adapter = PublicHtmlTelegramAdapter(client)

    with pytest.raises(ValueError, match="channel_ref"):
        await adapter.fetch(_request(channel_ref=channel_ref))
    await client.aclose()


def test_mtproto_grouping_uses_grouped_id_and_keeps_single_posts_separate():
    messages = [
        SimpleNamespace(
            id=10,
            grouped_id=None,
            date=datetime(2026, 7, 11, tzinfo=UTC),
            edit_date=None,
            message="one",
            media=None,
            entities=[],
        ),
        SimpleNamespace(
            id=11,
            grouped_id=700,
            date=datetime(2026, 7, 11, tzinfo=UTC),
            edit_date=None,
            message="album",
            media=object(),
            entities=[],
        ),
        SimpleNamespace(
            id=12,
            grouped_id=700,
            date=datetime(2026, 7, 11, tzinfo=UTC),
            edit_date=None,
            message="",
            media=object(),
            entities=[],
        ),
    ]

    grouped = group_mtproto_messages(messages, peer_id="-100900")

    assert [envelope.message_ids for envelope in grouped] == [(10,), (11, 12)]
    assert grouped[1].source_key == "-100900:album:700"
    assert grouped[1].text == "album"


def test_mtproto_grouping_assigns_contiguous_positions_to_media_only():
    messages = [
        _mtproto_message(11, grouped_id=700, media=None),
        _mtproto_message(12, grouped_id=700, media=SimpleNamespace()),
    ]

    grouped = group_mtproto_messages(messages, peer_id="-100900")

    assert [item.position for item in grouped[0].media] == [0]


async def test_mtproto_adapter_resolves_complete_credential_bundle_without_exposing_it():
    values = {
        "TELEGRAM_EDITOR_API_ID": "123456",
        "TELEGRAM_EDITOR_API_HASH": "api-hash",
        "TELEGRAM_EDITOR_SESSION": "session-material",
    }
    resolver = RecordingSecretResolver(values)
    factory = FakeTelegramClientFactory([_mtproto_message(51), _mtproto_message(52)])
    adapter = MtprotoTelegramAdapter(secret_resolver=resolver, client_factory=factory)

    result = await adapter.fetch(
        _request(
            after_id=50,
            before_id=60,
            api_id_secret_ref="TELEGRAM_EDITOR_API_ID",
            api_hash_secret_ref="TELEGRAM_EDITOR_API_HASH",
            session_secret_ref="TELEGRAM_EDITOR_SESSION",
        )
    )

    assert resolver.resolved == [
        "TELEGRAM_EDITOR_API_ID",
        "TELEGRAM_EDITOR_API_HASH",
        "TELEGRAM_EDITOR_SESSION",
    ]
    assert factory.credentials == (123456, "api-hash", "session-material")
    assert factory.client.last_kwargs["min_id"] == 50
    assert factory.client.last_kwargs["max_id"] == 60
    assert [item.anchor_message_id for item in result.envelopes] == [51, 52]
    assert all(value not in repr(result) for value in values.values())


async def test_mtproto_adapter_reports_reference_not_invalid_api_id_material():
    resolver = RecordingSecretResolver(
        {
            "TELEGRAM_EDITOR_API_ID": "not-a-number-secret",
            "TELEGRAM_EDITOR_API_HASH": "api-hash",
            "TELEGRAM_EDITOR_SESSION": "session-material",
        }
    )
    adapter = MtprotoTelegramAdapter(secret_resolver=resolver, client_factory=FakeTelegramClientFactory([]))

    with pytest.raises(ValueError) as error:
        await adapter.fetch(
            _request(
                api_id_secret_ref="TELEGRAM_EDITOR_API_ID",
                api_hash_secret_ref="TELEGRAM_EDITOR_API_HASH",
                session_secret_ref="TELEGRAM_EDITOR_SESSION",
            )
        )

    assert "TELEGRAM_EDITOR_API_ID" in str(error.value)
    assert "not-a-number-secret" not in str(error.value)
    assert "api-hash" not in str(error.value)
    assert "session-material" not in str(error.value)


@pytest.mark.parametrize(
    ("empty_reference", "expected_name"),
    [("ONE_API_HASH", "ONE_API_HASH"), ("ONE_SESSION", "ONE_SESSION")],
)
async def test_mtproto_adapter_rejects_empty_resolved_hash_or_session(empty_reference, expected_name):
    values = _credential_values("ONE")
    values[empty_reference] = "   "
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(values), client_factory=FakeTelegramClientFactory([])
    )

    with pytest.raises(ValueError) as error:
        await adapter.fetch(
            _request(
                api_id_secret_ref="ONE_API_ID",
                api_hash_secret_ref="ONE_API_HASH",
                session_secret_ref="ONE_SESSION",
            )
        )

    assert expected_name in str(error.value)
    assert "one-api-hash" not in str(error.value)
    assert "one-session-material" not in str(error.value)


async def test_mtproto_since_traverses_newest_first_without_using_offset_date():
    since = datetime(2026, 7, 11, 8, 51, tzinfo=UTC)
    factory = FakeTelegramClientFactory([_mtproto_message(52), _mtproto_message(51), _mtproto_message(50)])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        transport_page_size=3,
    )

    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            limit=2,
            since=since,
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )

    assert factory.client.last_kwargs["offset_date"] is None
    assert [item.anchor_message_id for item in result.envelopes] == [51, 52]
    assert result.complete is True


async def test_mtproto_activation_excludes_equal_timestamp_and_proves_boundary_on_full_page():
    boundary = datetime(2026, 7, 11, 8, 51, tzinfo=UTC)
    factory = FakeTelegramClientFactory([_mtproto_message(52), _mtproto_message(51)])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")), client_factory=factory
    )

    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            limit=2,
            activation_boundary_at=boundary,
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )

    assert [item.anchor_message_id for item in result.envelopes] == [52]
    assert result.complete is True
    assert factory.client.last_kwargs["offset_date"] is None


async def test_mtproto_snapshot_constrains_transport_before_newer_posts_consume_page_slots():
    factory = FakeTelegramClientFactory([_mtproto_message(52)])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        transport_page_size=2,
    )
    request = _request(
        channel_ref="one_channel",
        limit=2,
        api_id_secret_ref="ONE_API_ID",
        api_hash_secret_ref="ONE_API_HASH",
        session_secret_ref="ONE_SESSION",
    )
    first = await adapter.fetch(request)
    factory.client.messages = [_mtproto_message(message_id) for message_id in range(55, 50, -1)]

    pinned = await adapter.fetch(replace(request, snapshot_token=first.snapshot_token))

    assert factory.client.last_kwargs["max_id"] == 53
    assert [item.anchor_message_id for item in pinned.envelopes] == [51, 52]


async def test_mtproto_snapshot_transport_bound_keeps_stricter_caller_before_id():
    factory = FakeTelegramClientFactory([_mtproto_message(52)])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        transport_page_size=2,
    )
    request = _request(
        channel_ref="one_channel",
        limit=2,
        api_id_secret_ref="ONE_API_ID",
        api_hash_secret_ref="ONE_API_HASH",
        session_secret_ref="ONE_SESSION",
    )
    first = await adapter.fetch(request)
    factory.client.messages = [_mtproto_message(message_id) for message_id in range(55, 48, -1)]

    pinned = await adapter.fetch(replace(request, before_id=51, snapshot_token=first.snapshot_token))

    assert factory.client.last_kwargs["max_id"] == 51
    assert [item.anchor_message_id for item in pinned.envelopes] == [49, 50]


async def test_mtproto_rejects_mismatched_request_and_page_snapshots_before_transport():
    factory = FakeTelegramClientFactory([_mtproto_message(52)])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")), client_factory=factory
    )

    with pytest.raises(ValueError, match="snapshot"):
        await adapter.fetch(
            _request(
                channel_ref="one_channel",
                snapshot_token=_encode_token("snapshot", {"head": 52}),
                page_token=_encode_token(
                    "page", {"before": 50, "snapshot": 53, "pending_group_ids": []}
                ),
                api_id_secret_ref="ONE_API_ID",
                api_hash_secret_ref="ONE_API_HASH",
                session_secret_ref="ONE_SESSION",
            )
        )

    assert factory.client.last_kwargs == {}


async def test_mtproto_media_uses_exact_envelope_credential_references_for_same_channel(tmp_path):
    resolver = RecordingSecretResolver({**_credential_values("ONE"), **_credential_values("TWO", api_id="654321")})
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    factory = FakeTelegramClientFactory([message])
    adapter = MtprotoTelegramAdapter(secret_resolver=resolver, client_factory=factory)
    first_request = _request(
        channel_ref="one_channel",
        api_id_secret_ref="ONE_API_ID",
        api_hash_secret_ref="ONE_API_HASH",
        session_secret_ref="ONE_SESSION",
    )
    second_request = _request(
        channel_ref="one_channel",
        api_id_secret_ref="TWO_API_ID",
        api_hash_secret_ref="TWO_API_HASH",
        session_secret_ref="TWO_SESSION",
    )
    first = await adapter.fetch(first_request)
    await adapter.fetch(second_request)

    await adapter.materialize_media(first.envelopes[0], tmp_path)

    assert factory.calls[-1] == (123456, "one-api-hash", "one-session-material")
    assert factory.client.refetch_ids[-1] == 52
    assert factory.client.iter_download_media[-1] is message.media


async def test_mtproto_media_streaming_writes_only_inside_staging(tmp_path):
    outside = tmp_path.parent / "escaped-media"
    outside.write_bytes(b"outside")
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    factory = FakeTelegramClientFactory([message], download_return_path=outside)
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")), client_factory=factory
    )
    fetched = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )

    materialized = await adapter.materialize_media(fetched.envelopes[0], tmp_path)

    assert outside.read_bytes() == b"outside"
    assert materialized[0].path.parent == tmp_path


async def test_mtproto_media_streams_with_hard_bound_and_cleans_partial_file(tmp_path):
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    factory = FakeTelegramClientFactory([message], download_chunks=[b"1234", b"56"])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        max_media_bytes=5,
    )
    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )

    with pytest.raises(ValueError, match="exceeds 5 bytes"):
        await adapter.materialize_media(result.envelopes[0], tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_mtproto_media_sanitizes_secret_valued_refetch_and_stream_errors(tmp_path, error_type):
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    secret_error = error_type("one-api-hash one-session-material")
    factory = FakeTelegramClientFactory([message], stream_error=secret_error)
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")), client_factory=factory
    )
    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )

    with pytest.raises(RuntimeError) as error:
        await adapter.materialize_media(result.envelopes[0], tmp_path)

    assert result.envelopes[0].media[0].key in str(error.value)
    assert "one-api-hash" not in str(error.value)
    assert "one-session-material" not in str(error.value)


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_mtproto_media_sanitizes_secret_valued_client_enter_errors(tmp_path, error_type):
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    factory = FakeTelegramClientFactory([message])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")), client_factory=factory
    )
    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )
    factory.client.enter_error = error_type("one-api-hash one-session-material")

    with pytest.raises(RuntimeError, match="MTProto media client connection failed") as error:
        await adapter.materialize_media(result.envelopes[0], tmp_path)

    assert "one-api-hash" not in str(error.value)
    assert "one-session-material" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_mtproto_media_sanitizes_secret_valued_client_exit_errors_and_cleans_files(
    tmp_path, error_type
):
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    factory = FakeTelegramClientFactory([message])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")), client_factory=factory
    )
    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )
    factory.client.exit_error = error_type("one-api-hash one-session-material")

    with pytest.raises(RuntimeError, match="MTProto media client disconnection failed") as error:
        await adapter.materialize_media(result.envelopes[0], tmp_path)

    assert "one-api-hash" not in str(error.value)
    assert "one-session-material" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


async def test_mtproto_media_size_limit_survives_secret_valued_client_exit_error(tmp_path):
    message = _mtproto_message(52, media=SimpleNamespace(name="media-object"))
    factory = FakeTelegramClientFactory([message], download_chunks=[b"1234", b"56"])
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        max_media_bytes=5,
    )
    result = await adapter.fetch(
        _request(
            channel_ref="one_channel",
            api_id_secret_ref="ONE_API_ID",
            api_hash_secret_ref="ONE_API_HASH",
            session_secret_ref="ONE_SESSION",
        )
    )
    factory.client.exit_error = ValueError("one-api-hash one-session-material")

    with pytest.raises(ValueError, match="exceeds 5 bytes") as error:
        await adapter.materialize_media(result.envelopes[0], tmp_path)

    assert "one-api-hash" not in str(error.value)
    assert "one-session-material" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


async def test_mtproto_paging_does_not_emit_album_split_across_transport_pages():
    pages = [
        [_mtproto_message(13), _mtproto_message(12, grouped_id=700, media=SimpleNamespace())],
        [
            _mtproto_message(11, grouped_id=700, media=SimpleNamespace()),
            _mtproto_message(10),
        ],
    ]
    factory = FakeTelegramClientFactory(pages=pages)
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        transport_page_size=2,
    )
    request = _request(
        channel_ref="one_channel",
        limit=10,
        api_id_secret_ref="ONE_API_ID",
        api_hash_secret_ref="ONE_API_HASH",
        session_secret_ref="ONE_SESSION",
    )

    first = await adapter.fetch(request)
    second = await adapter.fetch(
        replace(request, snapshot_token=first.snapshot_token, page_token=first.next_page_token)
    )

    assert [item.message_ids for item in first.envelopes] == [(13,)]
    assert first.complete is False
    assert [item.message_ids for item in second.envelopes] == [(10,), (11, 12)]


async def test_mtproto_album_only_first_page_pins_snapshot_from_held_messages():
    pages = [
        [
            _mtproto_message(12, grouped_id=700, media=SimpleNamespace()),
            _mtproto_message(11, grouped_id=700, media=SimpleNamespace()),
        ],
        [_mtproto_message(10)],
    ]
    factory = FakeTelegramClientFactory(pages=pages)
    adapter = MtprotoTelegramAdapter(
        secret_resolver=RecordingSecretResolver(_credential_values("ONE")),
        client_factory=factory,
        transport_page_size=2,
    )
    request = _request(
        channel_ref="one_channel",
        limit=10,
        api_id_secret_ref="ONE_API_ID",
        api_hash_secret_ref="ONE_API_HASH",
        session_secret_ref="ONE_SESSION",
    )

    first = await adapter.fetch(request)
    second = await adapter.fetch(
        replace(request, snapshot_token=first.snapshot_token, page_token=first.next_page_token)
    )

    assert first.envelopes == ()
    assert first.complete is False
    assert [item.message_ids for item in second.envelopes] == [(10,), (11, 12)]


def test_source_registry_replaces_one_mode_and_rejects_unknown_modes():
    registry = TelegramSourceRegistry()
    first = object()
    replacement = object()

    registry.register("public_html", first)
    registry.register("public_html", replacement)

    assert registry.get("public_html") is replacement
    with pytest.raises(LookupError, match="unsupported Telegram access mode: mtproto_user"):
        registry.get("mtproto_user")


def _public_page(*message_ids: int) -> str:
    return "<html><body>" + "".join(
        f'''<div class="tgme_widget_message" data-post="example_channel/{message_id}">
        <div class="tgme_widget_message_text js-message_text">Post {message_id}</div>
        <time datetime="2026-07-11T08:{message_id % 60:02d}:00+00:00"></time></div>'''
        for message_id in message_ids
    ) + "</body></html>"


def _mtproto_message(
    message_id: int,
    *,
    grouped_id: int | None = None,
    media=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        grouped_id=grouped_id,
        date=datetime(2026, 7, 11, 8, message_id % 60, tzinfo=UTC),
        edit_date=None,
        message=f"Post {message_id}",
        media=media,
        entities=[],
        photo=media,
        video=None,
        file=SimpleNamespace(mime_type="image/jpeg", name=f"{message_id}.jpg") if media else None,
    )


class RecordingSecretResolver:
    def __init__(self, values: dict[str, str]):
        self.values = values
        self.resolved: list[str] = []

    def resolve(self, reference: str) -> str:
        self.resolved.append(reference)
        return self.values[reference]


class FakeTelegramClient:
    def __init__(
        self,
        messages: list[SimpleNamespace],
        *,
        pages: list[list[SimpleNamespace]] | None = None,
        download_return_path: Path | None = None,
        download_chunks: list[bytes] | None = None,
        refetch_error: Exception | None = None,
        stream_error: Exception | None = None,
        enter_error: Exception | None = None,
        exit_error: Exception | None = None,
    ):
        self.messages = messages
        self.pages = list(pages or [])
        self.last_kwargs: dict = {}
        self.download_return_path = download_return_path
        self.download_chunks = download_chunks or [b"downloaded"]
        self.refetch_error = refetch_error
        self.stream_error = stream_error
        self.enter_error = enter_error
        self.exit_error = exit_error
        self.refetch_ids: list[int] = []
        self.iter_download_media: list[object] = []

    async def __aenter__(self):
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self.exit_error is not None:
            raise self.exit_error
        return False

    async def get_messages(self, channel_ref: str, **kwargs):
        self.last_kwargs = {"channel_ref": channel_ref, **kwargs}
        if "ids" in kwargs:
            requested_ids = kwargs["ids"]
            self.refetch_ids.extend(requested_ids if isinstance(requested_ids, list) else [requested_ids])
            if self.refetch_error is not None:
                raise self.refetch_error
            if isinstance(requested_ids, list):
                return [item for item in self.messages if item.id in requested_ids]
            return next((item for item in self.messages if item.id == requested_ids), None)
        if self.pages:
            return self.pages.pop(0)
        messages = sorted(self.messages, key=lambda item: item.id, reverse=True)
        min_id = int(kwargs.get("min_id", 0))
        max_id = int(kwargs.get("max_id", 0))
        offset_id = int(kwargs.get("offset_id", 0))
        if min_id:
            messages = [item for item in messages if item.id > min_id]
        if max_id:
            messages = [item for item in messages if item.id < max_id]
        if offset_id:
            messages = [item for item in messages if item.id < offset_id]
        return messages[: int(kwargs.get("limit", len(messages)))]

    async def download_media(self, remote_ref: str, *, file: str):
        if self.download_return_path is not None:
            return str(self.download_return_path)
        Path(file).write_bytes(b"downloaded")
        return file

    async def iter_download(self, media, *, request_size: int):
        self.iter_download_media.append(media)
        if self.stream_error is not None:
            raise self.stream_error
        for chunk in self.download_chunks:
            yield chunk


class FakeTelegramClientFactory:
    def __init__(
        self,
        messages: list[SimpleNamespace] | None = None,
        *,
        pages: list[list[SimpleNamespace]] | None = None,
        download_return_path: Path | None = None,
        download_chunks: list[bytes] | None = None,
        refetch_error: Exception | None = None,
        stream_error: Exception | None = None,
    ):
        flattened = messages or [item for page in pages or [] for item in page]
        self.client = FakeTelegramClient(
            flattened,
            pages=pages,
            download_return_path=download_return_path,
            download_chunks=download_chunks,
            refetch_error=refetch_error,
            stream_error=stream_error,
        )
        self.credentials: tuple[int, str, str] | None = None
        self.calls: list[tuple[int, str, str]] = []

    def __call__(self, *, api_id: int, api_hash: str, session: str):
        self.credentials = (api_id, api_hash, session)
        self.calls.append(self.credentials)
        return self.client


def _credential_values(prefix: str, *, api_id: str = "123456") -> dict[str, str]:
    lowered = prefix.lower()
    return {
        f"{prefix}_API_ID": api_id,
        f"{prefix}_API_HASH": f"{lowered}-api-hash",
        f"{prefix}_SESSION": f"{lowered}-session-material",
    }
