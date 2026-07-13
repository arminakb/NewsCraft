from pathlib import Path
from uuid import uuid4

import httpx

from app.db.models import MediaAsset
from app.media.downloader import MediaDownloader

JPEG_BYTES = b"\xff\xd8\xff\xe0test-image\xff\xd9"


class FakeSession:
    def __init__(self, assets, *, fresh_asset=...):
        self.assets = assets
        self.fresh_asset = assets[0] if fresh_asset is ... and assets else fresh_asset
        self.flushed = False
        self.media_write_fenced = False

    async def scalars(self, stmt):
        return self.assets

    async def execute(self, stmt):
        if str(stmt).startswith("LOCK TABLE media_assets"):
            self.media_write_fenced = True

    async def scalar(self, stmt):
        return self.fresh_asset

    async def flush(self):
        self.flushed = True


def test_image_response_is_saved_with_checksum(tmp_path: Path):
    asset = _image_asset("https://cdn.example/image.jpg")
    downloader = MediaDownloader(
        FakeSession([asset]),
        http_client=_client_for_bytes(JPEG_BYTES, "image/jpeg"),
        media_root=tmp_path,
    )

    counts = _run(downloader)

    assert counts == {"checked": 1, "downloaded": 1, "skipped": 0, "failed": 0}
    assert asset.fetch_status == "downloaded"
    assert asset.checksum_sha256
    assert asset.storage_path
    assert Path(asset.storage_path).exists()
    assert Path(asset.storage_path).parent.name == asset.checksum_sha256[:2]


def test_non_image_content_for_image_candidate_is_skipped(tmp_path: Path):
    asset = _image_asset("https://cdn.example/not-image.jpg")
    downloader = MediaDownloader(
        FakeSession([asset]),
        http_client=_client_for_bytes(b"<html>not an image</html>", "text/html"),
        media_root=tmp_path,
    )

    counts = _run(downloader)

    assert counts["skipped"] == 1
    assert asset.fetch_status == "skipped"
    assert asset.storage_path is None


def test_large_response_above_max_size_is_skipped(tmp_path: Path):
    asset = _image_asset("https://cdn.example/large.jpg")
    downloader = MediaDownloader(
        FakeSession([asset]),
        http_client=_client_for_bytes(JPEG_BYTES, "image/jpeg", content_length=99),
        media_root=tmp_path,
        max_image_bytes=10,
    )

    counts = _run(downloader)

    assert counts["skipped"] == 1
    assert asset.fetch_status == "skipped"


def test_failed_url_marks_fetch_status_failed(tmp_path: Path):
    asset = _image_asset("https://cdn.example/down.jpg")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    downloader = MediaDownloader(
        FakeSession([asset]),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        media_root=tmp_path,
    )

    counts = _run(downloader)

    assert counts["failed"] == 1
    assert asset.fetch_status == "failed"


def test_download_missing_respects_limit(tmp_path: Path):
    assets = [_image_asset("https://cdn.example/1.jpg"), _image_asset("https://cdn.example/2.jpg")]
    downloader = MediaDownloader(
        FakeSession(assets),
        http_client=_client_for_bytes(JPEG_BYTES, "image/jpeg"),
        media_root=tmp_path,
    )

    counts = _run(downloader, limit=1)

    assert counts["checked"] == 1


def test_download_revalidates_under_retention_fence_before_writing(tmp_path: Path):
    asset = _image_asset("https://cdn.example/raced.jpg")
    session = FakeSession([asset], fresh_asset=None)
    downloader = MediaDownloader(
        session,
        http_client=_client_for_bytes(JPEG_BYTES, "image/jpeg"),
        media_root=tmp_path,
    )

    counts = _run(downloader)

    assert session.media_write_fenced is True
    assert counts == {"checked": 1, "downloaded": 0, "skipped": 1, "failed": 0}
    assert list(tmp_path.rglob("*.jpg")) == []


def _image_asset(url: str) -> MediaAsset:
    return MediaAsset(
        id=uuid4(),
        original_url=url,
        normalized_url=url,
        url_hash=url,
        kind="image",
        source_field="media_content",
        fetch_status="remote_only",
    )


def _client_for_bytes(content: bytes, content_type: str, content_length: int | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": content_type, "content-length": str(content_length or len(content))}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        return httpx.Response(200, headers=headers, content=content)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run(downloader: MediaDownloader, limit: int = 100) -> dict:
    import asyncio

    return asyncio.run(downloader.download_missing(limit=limit))
