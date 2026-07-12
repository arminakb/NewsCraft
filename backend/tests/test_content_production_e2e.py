from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content_production.briefs import EditorialBriefService
from app.content_production.dispatch import TelegramDispatchService
from app.content_production.media import MediaResolverService
from app.content_production.packages import TelegramPackageService
from app.content_production.quality import DraftQualityService
from app.content_production.repository import ContentProductionRepository
from app.content_production.sufficiency import ContentSufficiencyService
from app.content_production.telegram_drafts import TelegramDraftService
from app.db.models import ContentItem, MediaAsset


async def test_mocked_content_production_workflow_end_to_end():
    session = FakeSession()
    repository = ContentProductionRepository(session)
    media = _media_asset()
    item = _content_item(primary_image_id=media.id)

    request = await repository.create_request(topic="AI", max_candidates=1, created_by="operator")
    shortlist = await repository.add_shortlist_candidate(
        request_id=request.id,
        selection_execution_id=uuid4(),
        content_item_id=item.id,
        rank=1,
        score=99,
        selection_reason_json={"signals": ["test"]},
    )
    shortlist.approval_status = "approved"
    run = await repository.create_run(
        request_id=request.id,
        content_item_id=item.id,
        initial_state="shortlist_approved",
    )

    sufficiency = await ContentSufficiencyService(session).check_run(run, item)
    brief = await EditorialBriefService(session).create_brief(run=run, item=item, request=request)
    draft = await TelegramDraftService(session).create_draft(run=run, brief=brief)
    quality = await DraftQualityService(session).check_draft(run=run, draft=draft, brief=brief)
    visual = await MediaResolverService(session).resolve(run=run, item=item, media_assets=[media])
    package = await TelegramPackageService(session).build_package(
        run=run,
        draft=draft,
        quality_report=quality,
        visual_brief=visual,
    )

    assert sufficiency.status == "sufficient"
    assert quality.status == "passed"
    assert package.approval_status == "pending"
    assert package.package_json["dispatch_readiness"] == "blocked_pending_final_approval"

    await TelegramPackageService(session).approve(run=run, package=package)
    dispatch = await TelegramDispatchService(session).create_dispatch_request(run=run, package=package)

    assert package.approval_status == "approved"
    assert dispatch.status == "blocked"
    assert dispatch.dispatched_at is None
    assert run.state == "dispatch_failed"


def _content_item(primary_image_id):
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI feature launch",
        summary="The company launched a new AI feature for developers.",
        content_text="The company launched a new AI feature for developers. The rollout starts this week. " * 30,
        canonical_url="https://example.com/story",
        primary_image_id=primary_image_id,
        tags=["ai"],
        sort_at=datetime(2026, 7, 9, tzinfo=UTC),
        published_at=datetime(2026, 7, 9, tzinfo=UTC),
        date_parse_status="parsed",
        status="new",
        score=50,
        content_type="news",
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=True,
    )


def _media_asset():
    return MediaAsset(
        id=uuid4(),
        original_url="https://example.com/image.jpg",
        normalized_url="https://example.com/image.jpg",
        url_hash="hash",
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=675,
        source_field="media",
        fetch_status="fetched",
        media_quality="good",
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
