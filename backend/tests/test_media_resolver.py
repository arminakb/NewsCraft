from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.content_production.media import ImageGenerationResponse, MediaResolverService, build_visual_prompt
from app.db.models import Base, ContentItem, ContentProductionRun, MediaAsset, VisualBrief


def test_visual_briefs_table_is_registered():
    table = Base.metadata.tables["visual_briefs"]

    assert {
        "production_run_id",
        "status",
        "selected_media_asset_id",
        "needs_generation",
        "visual_prompt",
        "visual_style",
        "provider_name",
        "provider_request_json",
        "provider_result_json",
        "error_message",
        "created_at",
        "updated_at",
    }.issubset(table.columns.keys())
    assert "ix_visual_briefs_status" in {index.name for index in table.indexes}


def test_visual_briefs_migration_adds_table():
    migration = Path("alembic/versions/0010_visual_briefs.py").read_text()

    assert "visual_briefs" in migration
    assert "0009_draft_quality_reports" in migration
    assert "provider_request_json" in migration


async def test_media_resolver_selects_existing_primary_image():
    image = _media_asset(media_quality="good")
    item = _content_item(primary_image_id=image.id)
    run = _run(state="quality_passed")
    session = FakeSession()

    brief = await MediaResolverService(session).resolve(run=run, item=item, media_assets=[image])

    assert isinstance(brief, VisualBrief)
    assert brief.status == "selected"
    assert brief.selected_media_asset_id == image.id
    assert brief.needs_generation is False
    assert run.state == "media_ready"


async def test_media_resolver_creates_pending_visual_brief_when_no_image_provider():
    item = _content_item()
    run = _run(state="quality_passed")
    session = FakeSession()

    brief = await MediaResolverService(session).resolve(run=run, item=item, media_assets=[])

    assert brief.status == "pending"
    assert brief.needs_generation is True
    assert brief.provider_name == "none"
    assert brief.error_message == "no_image_generation_provider_configured"
    assert "Avoid logos" in brief.visual_prompt
    assert run.state == "image_generation_pending"


async def test_media_resolver_rejects_weak_image_and_uses_visual_prompt():
    weak = _media_asset(media_quality="low", width=64, height=64)
    item = _content_item(primary_image_id=weak.id)
    run = _run(state="quality_passed")
    session = FakeSession()

    brief = await MediaResolverService(session).resolve(run=run, item=item, media_assets=[weak])

    assert brief.selected_media_asset_id is None
    assert brief.needs_generation is True
    assert brief.status == "pending"


async def test_media_resolver_records_provider_generated_response():
    item = _content_item()
    run = _run(state="quality_passed")
    session = FakeSession()
    provider = FakeImageProvider(
        ImageGenerationResponse(status="generated", provider_result={"asset_id": "external-1"})
    )

    brief = await MediaResolverService(session, image_provider=provider).resolve(run=run, item=item, media_assets=[])

    assert brief.status == "generated"
    assert brief.provider_name == "fake-image"
    assert brief.provider_result_json == {"asset_id": "external-1"}
    assert run.state == "image_ready"


def test_visual_prompt_uses_title_and_context_without_claiming_generation():
    item = _content_item()

    prompt = build_visual_prompt(item)

    assert item.title in prompt
    assert "Avoid logos" in prompt


def _content_item(primary_image_id=None):
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI feature launch",
        summary="The company launched a new AI feature for developers.",
        canonical_url="https://example.com/story",
        primary_image_id=primary_image_id,
        date_parse_status="parsed",
        status="new",
        score=25,
        content_type="news",
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
    )


def _media_asset(media_quality="good", width=1200, height=675):
    return MediaAsset(
        id=uuid4(),
        original_url="https://example.com/image.jpg",
        normalized_url="https://example.com/image.jpg",
        url_hash="hash",
        kind="image",
        mime_type="image/jpeg",
        width=width,
        height=height,
        source_field="media",
        fetch_status="fetched",
        media_quality=media_quality,
    )


def _run(state: str):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=uuid4(),
        platform="telegram",
        state=state,
    )


class FakeImageProvider:
    provider_name = "fake-image"

    def __init__(self, response):
        self.response = response

    async def request_image(self, prompt: str, style: str | None = None):
        self.prompt = prompt
        self.style = style
        return self.response


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
