from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

import httpx
from sqlalchemy import select, text

from app.core.config import settings
from app.db.models import MediaAsset

IMAGE_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

MAX_IMAGE_BYTES = 15 * 1024 * 1024


class MediaDownloader:
    def __init__(
        self,
        session,
        http_client: httpx.AsyncClient | None = None,
        media_root: str | Path | None = None,
        max_image_bytes: int = MAX_IMAGE_BYTES,
    ):
        self.session = session
        self.http_client = http_client
        self.media_root = Path(media_root or settings.media_root)
        self.max_image_bytes = max_image_bytes

    async def download_missing(self, limit: int = 100) -> dict[str, int]:
        counts = {"checked": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        owns_client = self.http_client is None
        client = self.http_client or httpx.AsyncClient(timeout=30.0, follow_redirects=True, trust_env=True)
        try:
            assets = await self._load_missing_assets(limit)
            for asset in assets:
                counts["checked"] += 1
                result = await self._download_asset(client, asset)
                counts[result] += 1
            await self.session.flush()
            return counts
        finally:
            if owns_client:
                await client.aclose()

    async def _load_missing_assets(self, limit: int) -> list[MediaAsset]:
        stmt = (
            select(MediaAsset)
            .where(MediaAsset.fetch_status == "remote_only", MediaAsset.storage_path.is_(None))
            .order_by(MediaAsset.created_at)
            .limit(limit)
        )
        assets = await self.session.scalars(stmt)
        return list(assets)[:limit]

    async def _download_asset(self, client: httpx.AsyncClient, asset: MediaAsset) -> str:
        if asset.kind != "image":
            asset.fetch_status = "skipped"
            return "skipped"

        try:
            head = await client.head(asset.normalized_url, follow_redirects=True)
        except httpx.HTTPError:
            head = None

        if head is not None and head.status_code < 400:
            if _content_length_too_large(head.headers.get("content-length"), self.max_image_bytes):
                asset.fetch_status = "skipped"
                return "skipped"
            content_type = _normalized_content_type(head.headers.get("content-type"))
            if content_type and not content_type.startswith("image/"):
                asset.fetch_status = "skipped"
                return "skipped"

        try:
            response = await client.get(asset.normalized_url, follow_redirects=True)
            if response.status_code >= 400:
                asset.fetch_status = "failed"
                return "failed"
        except httpx.HTTPError:
            asset.fetch_status = "failed"
            return "failed"

        content = response.content
        content_type = _normalized_content_type(response.headers.get("content-type"))
        if len(content) > self.max_image_bytes:
            asset.fetch_status = "skipped"
            return "skipped"
        if not _is_supported_image(content, content_type):
            asset.fetch_status = "skipped"
            return "skipped"

        checksum = sha256(content).hexdigest()
        extension = _extension_for_image(content_type, asset.normalized_url)
        storage_path = self.media_root / checksum[:2] / f"{checksum}{extension}"
        await self.session.execute(text("LOCK TABLE media_assets IN ROW EXCLUSIVE MODE"))
        asset = await self.session.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.id == asset.id,
                MediaAsset.fetch_status == "remote_only",
                MediaAsset.storage_path.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if asset is None:
            return "skipped"
        _atomic_write(storage_path, content)

        asset.checksum_sha256 = checksum
        asset.storage_path = str(storage_path)
        asset.byte_length = len(content)
        asset.mime_type = content_type
        asset.fetch_status = "downloaded"
        return "downloaded"


def _content_length_too_large(value: str | None, max_size: int) -> bool:
    if not value:
        return False
    try:
        return int(value) > max_size
    except ValueError:
        return False


def _normalized_content_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower()


def _is_supported_image(content: bytes, content_type: str | None) -> bool:
    if content_type not in IMAGE_MIME_EXTENSIONS:
        return False
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def _extension_for_image(content_type: str | None, url: str) -> str:
    if content_type in IMAGE_MIME_EXTENSIONS:
        return IMAGE_MIME_EXTENSIONS[content_type]
    suffix = Path(url).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".bin"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_bytes(content)
    os.replace(temporary_path, path)
