import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.daily_bundle.exporter import export_daily_bundle


class CapturingSession:
    def __init__(self, items):
        self.items = items
        self.statement = None

    async def scalars(self, statement):
        self.statement = statement
        return self.items


async def test_export_daily_bundle_queries_date_range_and_writes_agent_folder(tmp_path):
    image_source = tmp_path / "source.jpg"
    image_source.write_bytes(b"image-bytes")
    start = datetime(2026, 7, 5, tzinfo=UTC)
    end = datetime(2026, 7, 6, tzinfo=UTC)
    items = [
        _content_item(
            "Stored image story",
            score=90,
            sort_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
            primary_media=SimpleNamespace(id=uuid4(), storage_path=str(image_source), normalized_url="https://e.test/a.jpg"),
        ),
        _content_item(
            "Remote image story",
            score=70,
            sort_at=datetime(2026, 7, 5, 8, tzinfo=UTC),
            primary_media=SimpleNamespace(id=uuid4(), storage_path=None, normalized_url="https://e.test/b.webp"),
        ),
        _content_item(
            "This is a very long headline " * 12,
            score=60,
            sort_at=datetime(2026, 7, 5, 7, tzinfo=UTC),
            primary_media=SimpleNamespace(id=uuid4(), storage_path=None, normalized_url=None),
        ),
    ]
    session = CapturingSession(items)
    output_path = tmp_path / "bundle"
    (output_path / "articles").mkdir(parents=True)
    (output_path / "images").mkdir()
    (output_path / "articles/stale.md").write_text("stale", encoding="utf-8")
    (output_path / "images/stale.jpg").write_bytes(b"stale")

    result = await export_daily_bundle(session, start, end, output_path, limit=25)

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "content_items.sort_at >= " in sql
    assert "content_items.sort_at < " in sql
    assert "ORDER BY content_items.score DESC, content_items.sort_at DESC" in sql
    assert "LIMIT " in sql
    assert result["item_count"] == 3
    assert (output_path / "index.md").exists()
    assert (output_path / "sources.json").exists()
    assert (output_path / "articles/001-stored-image-story.md").exists()
    assert (output_path / "articles/002-remote-image-story.md").exists()
    assert len(list(output_path.glob("articles/003-*.md"))[0].name) <= 100
    assert (output_path / "images/001.jpg").read_bytes() == b"image-bytes"
    assert not (output_path / "articles/stale.md").exists()
    assert not (output_path / "images/stale.jpg").exists()

    payload = json.loads((output_path / "items.json").read_text(encoding="utf-8"))
    sources = json.loads((output_path / "sources.json").read_text(encoding="utf-8"))
    assert payload[0]["title"] == "Stored image story"
    assert payload[0]["image_path"] == "images/001.jpg"
    assert payload[1]["image_url"] == "https://e.test/b.webp"
    assert sources == [
        {
            "source_platform": "gdelt",
            "source_name": "GDELT",
            "source_domain": "example.com",
            "item_count": 3,
        }
    ]
    assert "Full content for Stored image story" in (
        output_path / "articles/001-stored-image-story.md"
    ).read_text(encoding="utf-8")
    assert "Stored image story" in (output_path / "index.md").read_text(encoding="utf-8")


def _content_item(title: str, score: int, sort_at: datetime, primary_media):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        canonical_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        published_at=sort_at,
        sort_at=sort_at,
        score=score,
        summary=f"Summary for {title}",
        content_text=f"Full content for {title}",
        language_code="en",
        direction="ltr",
        authors=["Reporter"],
        tags=["AI"],
        content_type="article",
        rewrite_bucket="timely",
        quality_status="needs_review",
        freshness_bucket="fresh",
        source_tier="standard",
        primary_image_id=primary_media.id,
        primary_media=primary_media,
        metrics={"source_name": "Example"},
        classification_metadata={
            "source_platform": "gdelt",
            "source_name": "GDELT",
            "source_domain": "example.com",
        },
        score_breakdown={"freshness": 10},
        ranking_metadata={"rank_reason": "test"},
    )
