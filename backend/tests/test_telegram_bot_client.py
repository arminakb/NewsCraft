from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from app.publishing.telegram.client import (
    TelegramAmbiguousError,
    TelegramBotClient,
    TelegramPermanentError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.contracts import TelegramPublishOperation, TelegramUploadMetadata

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyzABCDEFGH"


def _operation(method: str, tmp_path: Path | None = None) -> TelegramPublishOperation:
    if method == "sendMessage":
        fields = {"chat_id": "@target", "text": "hello", "parse_mode": "HTML"}
        paths = ()
    elif method == "sendMediaGroup":
        assert tmp_path is not None
        first, second = tmp_path / "a.jpg", tmp_path / "b.mp4"
        first.write_bytes(b"photo")
        second.write_bytes(b"video")
        fields = {
            "chat_id": "@target",
            "media": [
                {"type": "photo", "media": "attach://file0"},
                {"type": "video", "media": "attach://file1"},
            ],
        }
        paths = (first, second)
        uploads = (
            TelegramUploadMetadata(
                "file0", "upload-0.jpg", "image/jpeg", "photo", hashlib.sha256(b"photo").hexdigest()
            ),
            TelegramUploadMetadata(
                "file1", "upload-1.mp4", "video/mp4", "video", hashlib.sha256(b"video").hexdigest()
            ),
        )
    else:
        assert tmp_path is not None
        path = tmp_path / "a.jpg"
        path.write_bytes(b"photo")
        fields = {"chat_id": "@target", "photo": "attach://file0", "caption": "hello"}
        paths = (path,)
        uploads = (
            TelegramUploadMetadata(
                "file0", "upload-0.jpg", "image/jpeg", "photo", hashlib.sha256(b"photo").hexdigest()
            ),
        )
    if method == "sendMessage":
        uploads = ()
    return TelegramPublishOperation(0, "op-0", method, fields, paths, "a" * 64, uploads)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "result", "expected"),
    [
        ("sendMessage", {"message_id": 11}, (11,)),
        ("sendPhoto", {"message_id": 12}, (12,)),
        ("sendMediaGroup", [{"message_id": 13}, {"message_id": 14}], (13, 14)),
    ],
)
async def test_execute_normalizes_message_ids_and_uses_json_or_multipart(tmp_path, method, result, expected):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"ok": True, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        response = await TelegramBotClient(http, base_url="https://api.telegram.org").execute(
            _operation(method, tmp_path), TOKEN
        )

    assert response.remote_message_ids == expected
    assert TOKEN not in repr(response)
    assert ("application/json" in seen["content_type"]) is (method == "sendMessage")
    assert TOKEN in seen["url"]


@pytest.mark.asyncio
async def test_multipart_uses_safe_deterministic_upload_metadata(tmp_path):
    path = tmp_path / "customer-secret-name.png"
    path.write_bytes(b"photo")
    operation = TelegramPublishOperation(
        0,
        "op-0",
        "sendPhoto",
        {"chat_id": "@target", "photo": "attach://file0"},
        (path,),
        "a" * 64,
        (
            TelegramUploadMetadata(
                "file0", "upload-0.png", "image/png", "photo", hashlib.sha256(b"photo").hexdigest()
            ),
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"customer-secret-name" not in request.content
        assert b'filename="upload-0.png"' in request.content
        assert b"Content-Type: image/png" in request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await TelegramBotClient(http).execute(operation, TOKEN)


@pytest.mark.asyncio
async def test_multipart_without_hashed_upload_metadata_fails_before_transport(tmp_path):
    path = tmp_path / "asset.jpg"
    path.write_bytes(b"photo")
    operation = TelegramPublishOperation(
        0, "op-0", "sendPhoto", {"chat_id": "@target", "photo": "attach://file0"}, (path,), "a" * 64
    )
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramPermanentError, match="upload plan"):
            await TelegramBotClient(http).execute(operation, TOKEN)
    assert called is False


@pytest.mark.asyncio
async def test_multipart_hashes_and_dispatches_each_single_open_handle(tmp_path, monkeypatch):
    operation = _operation("sendPhoto", tmp_path)
    original_open = Path.open
    opens = 0

    def tracked_open(path, *args, **kwargs):
        nonlocal opens
        opens += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"photo" in request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await TelegramBotClient(http).execute(operation, TOKEN)
    assert opens == 1


@pytest.mark.asyncio
async def test_multipart_rejects_bytes_changed_after_plan_without_dispatch(tmp_path):
    path = tmp_path / "asset.jpg"
    path.write_bytes(b"changed")
    operation = TelegramPublishOperation(
        0,
        "op-0",
        "sendPhoto",
        {"chat_id": "@target", "photo": "attach://file0"},
        (path,),
        "a" * 64,
        (
            TelegramUploadMetadata(
                attach_name="file0",
                filename="upload-0.jpg",
                mime_type="image/jpeg",
                media_type="photo",
                checksum_sha256="a" * 64,
            ),
        ),
    )
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramPermanentError, match="upload"):
            await TelegramBotClient(http).execute(operation, TOKEN)
    assert called is False


@pytest.mark.asyncio
async def test_rate_limit_exposes_retry_after_without_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "description": f"retry token={TOKEN}", "parameters": {"retry_after": 17}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramRateLimited) as caught:
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)

    assert caught.value.retry_after == 17
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value.metadata)


@pytest.mark.asyncio
async def test_bot_error_code_429_is_rate_limited_even_with_http_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": 429, "description": "wait", "parameters": {"retry_after": 17}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramRateLimited) as caught:
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)
    assert caught.value.retry_after == 17


@pytest.mark.asyncio
async def test_malformed_retry_after_is_clamped_positive():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "parameters": {"retry_after": -5}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramRateLimited) as caught:
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)
    assert caught.value.retry_after == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectError("cannot connect"), TelegramRetryableBeforeDispatch),
        (httpx.ReadTimeout(f"timed out {TOKEN}"), TelegramAmbiguousError),
    ],
)
async def test_transport_errors_are_classified_and_redacted(error, expected):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(expected) as caught:
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)

    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value.metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [(500, TelegramAmbiguousError), (503, TelegramAmbiguousError), (400, TelegramPermanentError)],
)
async def test_http_errors_are_classified_and_redacted(status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"ok": False, "description": f"bad {TOKEN}", "parameters": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(expected) as caught:
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)

    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value.metadata)


@pytest.mark.asyncio
async def test_success_metadata_is_sanitized_and_response_shape_is_validated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}, "description": TOKEN})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)
    assert TOKEN not in repr(result.response_metadata)
    assert result.response_metadata == {
        "http_status": 200,
        "ok": True,
        "method": "sendMessage",
        "result_count": 1,
    }

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": TOKEN}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as http:
        with pytest.raises(TelegramAmbiguousError):
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", [0, -1, True])
async def test_message_ids_must_be_positive_integers(message_id):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramAmbiguousError):
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)


@pytest.mark.asyncio
async def test_media_group_result_count_must_match_files(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": [{"message_id": 1}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramAmbiguousError):
            await TelegramBotClient(http).execute(_operation("sendMediaGroup", tmp_path), TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "result"),
    [
        ("sendMessage", [{"message_id": 1}]),
        ("sendMediaGroup", {"message_id": 1}),
    ],
)
async def test_success_result_shape_must_match_operation(tmp_path, method, result):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramAmbiguousError):
            await TelegramBotClient(http).execute(_operation(method, tmp_path), TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.PoolTimeout("pool"), TelegramRetryableBeforeDispatch),
        (httpx.WriteTimeout("write"), TelegramAmbiguousError),
        (httpx.RemoteProtocolError("protocol"), TelegramAmbiguousError),
    ],
)
async def test_additional_transport_errors_are_classified(error, expected):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise error

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(expected):
            await TelegramBotClient(http).execute(_operation("sendMessage"), TOKEN)


@pytest.mark.asyncio
async def test_get_chat_is_redacted_and_classified():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"id": -1001, "type": "channel", "username": "target", "title": TOKEN, "raw": TOKEN},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await TelegramBotClient(http).get_chat("@target", TOKEN)
    assert result["id"] == -1001
    assert TOKEN not in repr(result)
    assert set(result) == {"id", "type", "username", "title"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {},
        {"id": True, "type": "channel"},
        {"id": 0, "type": "channel"},
        {"id": -1001, "type": ""},
        {"id": -1001, "type": "unsupported"},
    ],
)
async def test_get_chat_rejects_malformed_success_identity(result):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(TelegramAmbiguousError):
            await TelegramBotClient(http).get_chat("@target", TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "get_chat"])
async def test_bot_5xx_error_code_on_http_200_is_ambiguous(method):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error_code": 503, "description": "upstream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramBotClient(http)
        with pytest.raises(TelegramAmbiguousError):
            if method == "execute":
                await client.execute(_operation("sendMessage"), TOKEN)
            else:
                await client.get_chat("@target", TOKEN)
