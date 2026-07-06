from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import ContentItem


async def export_daily_bundle(
    session,
    start: datetime,
    end: datetime,
    output_path: Path,
    limit: int = 250,
) -> dict[str, Any]:
    stmt = (
        select(ContentItem)
        .options(selectinload(ContentItem.primary_media))
        .where(ContentItem.sort_at >= start, ContentItem.sort_at < end)
        .order_by(ContentItem.score.desc(), ContentItem.sort_at.desc())
        .limit(limit)
    )
    rows = await session.scalars(stmt)
    items = list(rows)

    output_path.mkdir(parents=True, exist_ok=True)
    articles_path = output_path / "articles"
    images_path = output_path / "images"
    _clear_directory(articles_path)
    _clear_directory(images_path)
    articles_path.mkdir(parents=True, exist_ok=True)
    images_path.mkdir(parents=True, exist_ok=True)

    payload: list[dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        article_filename = f"{rank:03d}-{_slugify(getattr(item, 'title', None) or 'untitled')}.md"
        image_path, image_url = _materialize_primary_image(item, rank, images_path)
        record = _item_record(item, rank, f"articles/{article_filename}", image_path, image_url)
        payload.append(record)
        (articles_path / article_filename).write_text(_article_markdown(record), encoding="utf-8")

    (output_path / "items.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (output_path / "sources.json").write_text(
        json.dumps(_sources_payload(payload), ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (output_path / "index.md").write_text(_index_markdown(start, end, payload), encoding="utf-8")
    return {"output_path": str(output_path), "item_count": len(payload)}


def _item_record(item, rank: int, article_path: str, image_path: str | None, image_url: str | None) -> dict[str, Any]:
    metadata = getattr(item, "classification_metadata", None) or {}
    primary_media = getattr(item, "primary_media", None)
    return {
        "id": str(getattr(item, "id", "")),
        "rank": rank,
        "title": getattr(item, "title", None),
        "url": getattr(item, "canonical_url", None),
        "source_platform": metadata.get("source_platform"),
        "source_name": metadata.get("source_name"),
        "source_domain": metadata.get("source_domain"),
        "published_at": getattr(item, "published_at", None),
        "sort_at": getattr(item, "sort_at", None),
        "score": int(getattr(item, "score", 0) or 0),
        "summary": getattr(item, "summary", None),
        "content_text": getattr(item, "content_text", None),
        "language_code": getattr(item, "language_code", None),
        "direction": getattr(item, "direction", None),
        "authors": getattr(item, "authors", None) or [],
        "tags": getattr(item, "tags", None) or [],
        "content_type": getattr(item, "content_type", None),
        "rewrite_bucket": getattr(item, "rewrite_bucket", None),
        "quality_status": getattr(item, "quality_status", None),
        "freshness_bucket": getattr(item, "freshness_bucket", None),
        "source_tier": getattr(item, "source_tier", None),
        "primary_image_id": str(getattr(item, "primary_image_id", "") or "") or None,
        "image_path": image_path,
        "image_url": image_url,
        "article_path": article_path,
        "metrics": getattr(item, "metrics", None) or {},
        "classification_metadata": metadata,
        "score_breakdown": getattr(item, "score_breakdown", None) or {},
        "ranking_metadata": getattr(item, "ranking_metadata", None) or {},
        "primary_media": {
            "id": str(getattr(primary_media, "id", "")),
            "normalized_url": getattr(primary_media, "normalized_url", None),
            "storage_path": getattr(primary_media, "storage_path", None),
        }
        if primary_media
        else None,
    }


def _materialize_primary_image(item, rank: int, images_path: Path) -> tuple[str | None, str | None]:
    media = getattr(item, "primary_media", None)
    if not media:
        return None, None
    storage_path = getattr(media, "storage_path", None)
    if storage_path and Path(storage_path).exists():
        source_path = Path(storage_path)
        suffix = source_path.suffix or ".bin"
        destination = images_path / f"{rank:03d}{suffix}"
        shutil.copyfile(source_path, destination)
        return f"images/{destination.name}", None
    return None, getattr(media, "normalized_url", None)


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _article_markdown(record: dict[str, Any]) -> str:
    image = record["image_path"] or record["image_url"] or ""
    provenance = {
        "id": record["id"],
        "source_platform": record["source_platform"],
        "source_name": record["source_name"],
        "source_domain": record["source_domain"],
        "score_breakdown": record["score_breakdown"],
        "ranking_metadata": record["ranking_metadata"],
        "classification_metadata": record["classification_metadata"],
    }
    return "\n".join(
        [
            f"# {record['title'] or 'Untitled'}",
            "",
            f"- URL: {record['url'] or ''}",
            f"- Source: {_source_label(record)}",
            f"- Published: {_format_datetime(record['published_at'])}",
            f"- Sort date: {_format_datetime(record['sort_at'])}",
            f"- Score: {record['score']}",
            f"- Image: {image}",
            f"- Tags: {', '.join(record['tags'])}",
            "",
            "## Summary",
            "",
            record["summary"] or "",
            "",
            "## Article Text",
            "",
            record["content_text"] or "",
            "",
            "## Provenance",
            "",
            "```json",
            json.dumps(provenance, ensure_ascii=False, indent=2, default=_json_default),
            "```",
            "",
        ]
    )


def _index_markdown(start: datetime, end: datetime, items: list[dict[str, Any]]) -> str:
    lines = [
        f"# Daily News Bundle: {start.date().isoformat()} to {end.date().isoformat()}",
        "",
        f"Items: {len(items)}",
        "",
        "## Articles",
        "",
    ]
    for item in items:
        image = item["image_path"] or item["image_url"] or ""
        lines.append(
            f"{item['rank']}. [{item['title'] or 'Untitled'}]({item['article_path']}) "
            f"- score {item['score']} - {_source_label(item)} - {_format_datetime(item['sort_at'])} - {image}"
        )
    lines.append("")
    return "\n".join(lines)


def _sources_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str | None, str | None, str | None], int] = {}
    for item in items:
        key = (item["source_platform"], item["source_name"], item["source_domain"])
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "source_platform": source_platform,
            "source_name": source_name,
            "source_domain": source_domain,
            "item_count": count,
        }
        for (source_platform, source_name, source_domain), count in sorted(
            counts.items(), key=lambda pair: (pair[0][0] or "", pair[0][1] or "", pair[0][2] or "")
        )
    ]


def _source_label(record: dict[str, Any]) -> str:
    return str(record["source_name"] or record["source_platform"] or record["source_domain"] or "unknown")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "item")[:80].strip("-") or "item"


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else ""


def _json_default(value: Any) -> str | int | float:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
