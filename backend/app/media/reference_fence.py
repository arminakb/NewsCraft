from __future__ import annotations

from typing import Any

from sqlalchemy import text


async def fence_platform_revision_media_write(session: Any) -> None:
    """Serialize media-backed revision writers with retention's table fence."""

    await session.execute(text("LOCK TABLE media_assets, platform_variant_revisions IN ROW EXCLUSIVE MODE"))
