from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import httpx
from sqlalchemy import select, text

from app.core.config import settings
from app.core.safe_http import SafeHttpClient, SafeHttpError
from app.db.models import MediaAsset
from app.media.atomic_files import atomic_write
from app.media.imagecodec import normalized_content_type, sniff_image_format
from app.normalization.url_safety import UnsafeUrlError, validate_public_http_url

IMAGE_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

MAX_IMAGE_BYTES = 15 * 1024 * 1024


class MediaDownloader:
    """Fetch remote media through the pinned, size-capped public HTTP boundary.

    Media URLs are third-party input: they are harvested from remote feed
    bodies, so every request must go through `SafeHttpClient` (DNS pinning,
    public-address-only, per-hop redirect revalidation, bounded body) with the
    shared deny-list applied to the requested and the final URL.
    """

    def __init__(
        self,
        session,
        http_client: SafeHttpClient | None = None,
        media_root: str | Path | None = None,
        max_image_bytes: int = MAX_IMAGE_BYTES,
    ):
        self.session = session
        self.http_client = http_client
        self.media_root = Path(media_root or settings.media_root)
        self.max_image_bytes = max_image_bytes

    async def download_missing(self, limit: int = 100) -> dict[str, int]:
        if self.http_client is not None:
            return await self._download_missing(self.http_client, limit)
        async with SafeHttpClient(timeout=30.0, max_response_bytes=self.max_image_bytes) as client:
            return await self._download_missing(client, limit)

    async def _download_missing(self, client: SafeHttpClient, limit: int) -> dict[str, int]:
        counts = {"checked": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        assets = await self._load_missing_assets(limit)
        for asset in assets:
            counts["checked"] += 1
            result = await self._download_asset(client, asset)
            counts[result] += 1
        await self.session.flush()
        return counts

    async def _load_missing_assets(self, limit: int) -> list[MediaAsset]:
        stmt = (
            select(MediaAsset)
            .where(MediaAsset.fetch_status == "remote_only", MediaAsset.storage_path.is_(None))
            .order_by(MediaAsset.created_at)
            .limit(limit)
        )
        assets = await self.session.scalars(stmt)
        return list(assets)[:limit]

    async def _download_asset(self, client: SafeHttpClient, asset: MediaAsset) -> str:
        if asset.kind != "image":
            asset.fetch_status = "skipped"
            return "skipped"

        try:
            validate_public_http_url(asset.normalized_url)
        except UnsafeUrlError:
            asset.fetch_status = "skipped"
            return "skipped"

        try:
            response = await client.get(asset.normalized_url, follow_redirects=True)
        except SafeHttpError:
            # Rejected target, oversized body, or redirect loop: never retried,
            # and reported as "skipped" so the stored status cannot be read as
            # an internal-host probe.
            asset.fetch_status = "skipped"
            return "skipped"
        except httpx.HTTPError:
            asset.fetch_status = "failed"
            return "failed"

        try:
            validate_public_http_url(str(response.url))
        except UnsafeUrlError:
            asset.fetch_status = "skipped"
            return "skipped"

        if response.status_code >= 400:
            asset.fetch_status = "failed"
            return "failed"

        content = response.content
        content_type = normalized_content_type(response.headers.get("content-type"))
        if len(content) > self.max_image_bytes:
            asset.fetch_status = "skipped"
            return "skipped"
        if not _is_supported_image(content, content_type):
            asset.fetch_status = "skipped"
            return "skipped"

        checksum = sha256(content).hexdigest()
        assert content_type is not None
        extension = IMAGE_MIME_EXTENSIONS[content_type]
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
        atomic_write(storage_path, content)

        asset.checksum_sha256 = checksum
        asset.storage_path = str(storage_path)
        asset.byte_length = len(content)
        asset.mime_type = content_type
        asset.fetch_status = "downloaded"
        return "downloaded"


def _is_supported_image(content: bytes, content_type: str | None) -> bool:
    if content_type not in IMAGE_MIME_EXTENSIONS:
        return False
    return sniff_image_format(content) == content_type
