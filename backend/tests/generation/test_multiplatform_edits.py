import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.automations.telegram.handlers import sha256_canonical
from app.generation.editorial_service import (
    ApprovalRequest,
    EditorialService,
    EditVariantRequest,
    InvalidGenerationRequest,
    RevisionConflict,
)
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.multiplatform import ordered_distinct_citations
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramEditPayload,
    InstagramVariantPayload,
    ManualPlatformEditRequest,
    XVariantPayload,
)
from app.generation.revision_fence import RegenerationFenceConflict
from app.generation.telegram_schema import TelegramRewriteOutput, TelegramVariantContent
from app.research.schemas import CitationRef
from app.stories.models import StoryRevision


def grounded_instagram():
    return InstagramVariantPayload.model_validate(
        {
            "hook": "Grounded",
            "caption": "Grounded caption",
            "cta": "Read more",
            "hashtags": [],
            "alt_text": "Summary card",
            "carousel": [],
            "citations": [
                {
                    "evidence_key": "evidence:one",
                    "evidence_snapshot_id": uuid4(),
                    "source_url": "https://example.com/report",
                    "locator": "chars:0-8",
                    "excerpt_sha256": "a" * 64,
                }
            ],
            "manual_checklist": ["Verify copy"],
        }
    )


def test_manual_edit_is_discriminated_and_binds_base_revision_hash():
    content = grounded_instagram()
    request = ManualPlatformEditRequest(
        base_revision_id=uuid4(),
        base_content_hash="b" * 64,
        payload=InstagramEditPayload(platform="instagram", content=content),
        evidence_map=ordered_distinct_citations(content),
        edit_note="Shorten the caption",
    )

    assert request.payload.platform == "instagram"
    assert request.payload.content == content
    with pytest.raises(ValidationError):
        ManualPlatformEditRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "payload": {"platform": "x", "content": content.model_dump(mode="json")},
            }
        )


def _service_fixture():
    evidence_text = "Evidence"
    snapshot_id = uuid4()
    citation = CitationRef(
        evidence_key="evidence:one",
        evidence_snapshot_id=snapshot_id,
        source_url="https://example.com/report",
        locator="chars:0-8",
        excerpt_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
    )
    payload = InstagramVariantPayload.model_validate(
        {
            "hook": "Grounded",
            "caption": "Grounded caption",
            "cta": "Read more",
            "hashtags": [],
            "alt_text": "Summary card",
            "carousel": [],
            "citations": [citation.model_dump(mode="json")],
            "manual_checklist": ["Verify copy"],
        }
    )
    story_id, story_revision_id, pack_id, variant_id = uuid4(), uuid4(), uuid4(), uuid4()
    story_revision = StoryRevision(
        id=story_revision_id,
        story_id=story_id,
        revision_number=1,
        narrative="Grounded story",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[citation.model_dump(mode="json")],
        created_by="generation",
    )
    pack = ContentPack(id=pack_id, story_revision_id=story_revision_id, brand_profile_id=uuid4(), status="draft")
    variant = PlatformVariant(id=variant_id, content_pack_id=pack_id, platform="instagram")
    parent = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant_id,
        parent_revision_id=None,
        generation_attempt_id=uuid4(),
        revision_number=1,
        content=payload.model_dump(mode="json"),
        content_hash=sha256_canonical(
            {
                "content": payload.model_dump(mode="json"),
                "evidence_map": [citation.model_dump(mode="json")],
            }
        ),
        evidence_map=[citation.model_dump(mode="json")],
        validation_results=[],
        approval_state="approved",
        created_by="generation",
    )
    snapshot = SimpleNamespace(
        id=snapshot_id,
        story_id=story_id,
        evidence_key=citation.evidence_key,
        content_item_id=None,
        title="Evidence",
        content_text=evidence_text,
        content_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
        source_url=str(citation.source_url),
        authors=[],
        published_at=None,
        captured_at=datetime.now(UTC),
    )
    return payload, citation, story_revision, pack, variant, parent, snapshot


class _Session:
    def __init__(self, *, scalar_values, objects, snapshots, media_links=None, media_assets=None):
        self.scalar_values = list(scalar_values)
        self.objects = objects
        self.snapshots = snapshots
        self.media_links = list(media_links or [])
        self.media_assets = list(media_assets or [])
        self.scalars_calls = 0
        self.scalar_statements = []
        self.added = []

    @asynccontextmanager
    async def begin(self):
        yield

    async def scalar(self, statement):
        return self.scalar_values.pop(0)

    async def get(self, model, identifier):
        return self.objects.get((model, identifier))

    async def scalars(self, statement):
        from app.jobs.models import WorkflowJob

        if statement.column_descriptions[0].get("entity") is WorkflowJob:
            return []
        self.scalars_calls += 1
        self.scalar_statements.append(statement)
        return {
            1: self.snapshots,
            2: self.media_links,
            3: self.media_assets,
        }.get(self.scalars_calls, [])

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


def _edit_request(parent, payload, citation, *, platform="instagram", evidence=None):
    return ManualPlatformEditRequest.model_validate(
        {
            "base_revision_id": str(parent.id),
            "base_content_hash": parent.content_hash,
            "payload": {"platform": platform, "content": payload.model_dump(mode="json")},
            "evidence_map": evidence or [citation.model_dump(mode="json")],
            "edit_note": "Operator edit",
        }
    )


@pytest.mark.asyncio
async def test_telegram_edit_rejects_manual_platform_before_loading_or_parsing_parent():
    variant = PlatformVariant(id=uuid4(), content_pack_id=uuid4(), platform="instagram")

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        async def scalar(self, statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return variant
            raise AssertionError("manual-platform conflict must stop before parent loading")

    request = EditVariantRequest(
        base_revision_id=uuid4(),
        base_content_hash="b" * 64,
        content=TelegramRewriteOutput(body="Grounded", parse_mode="HTML", buttons=[]),
        media_asset_ids=[],
        edit_note="Operator edit",
    )
    session = Session()

    with pytest.raises(RevisionConflict, match="platform"):
        await EditorialService(session).edit_variant(variant.id, request)

    assert session.scalar_calls == 1


@pytest.mark.asyncio
async def test_editorial_telegram_and_manual_writers_reject_live_regeneration_fence(monkeypatch):
    payload, citation, _story_revision, _pack, manual_variant, parent, _snapshot = _service_fixture()
    telegram_variant = PlatformVariant(id=uuid4(), content_pack_id=uuid4(), platform="telegram")

    class Session:
        def __init__(self, variant):
            self.variant = variant
            self.scalar_calls = 0
            self.added = []

        async def scalar(self, statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return self.variant
            raise AssertionError("foreign fence must stop before parent loading")

        def add(self, value):
            self.added.append(value)

    async def reject_fence(session, **kwargs):
        raise RegenerationFenceConflict("Variant regeneration is in progress")

    monkeypatch.setattr(
        "app.generation.editorial_service.require_revision_write_allowed",
        reject_fence,
    )
    telegram_request = EditVariantRequest(
        base_revision_id=uuid4(),
        base_content_hash="b" * 64,
        content=TelegramRewriteOutput(body="Grounded", parse_mode="HTML", buttons=[]),
        media_asset_ids=[],
        edit_note="Operator edit",
    )
    telegram_session = Session(telegram_variant)
    with pytest.raises(RevisionConflict, match="regeneration"):
        await EditorialService(telegram_session).edit_variant(telegram_variant.id, telegram_request)

    manual_session = Session(manual_variant)
    with pytest.raises(RevisionConflict, match="regeneration"):
        await EditorialService(manual_session).edit_manual_platform_variant(
            manual_variant.id,
            _edit_request(parent, payload, citation),
        )

    assert telegram_session.added == manual_session.added == []


@pytest.mark.asyncio
async def test_manual_edit_path_creates_immutable_pending_child_and_preserves_approved_parent():
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    session = _Session(
        scalar_values=[variant, parent],
        objects={(ContentPack, pack.id): pack, (StoryRevision, story_revision.id): story_revision},
        snapshots=[snapshot],
    )

    child = await EditorialService(session).edit_manual_platform_variant(
        variant.id,
        _edit_request(parent, payload, citation),
    )

    assert child.parent_revision_id == parent.id
    assert child.generation_attempt_id is None
    assert child.approval_state == "pending_review"
    assert parent.approval_state == "approved"
    assert session.added == [child]


@pytest.mark.parametrize(
    ("platform", "payload_factory", "expected_code"),
    [
        (
            "instagram",
            lambda citation: InstagramVariantPayload.model_validate(
                {
                    "hook": "Grounded",
                    "caption": "Grounded caption",
                    "cta": "Read more",
                    "hashtags": [" "],
                    "alt_text": "Summary card",
                    "carousel": [],
                    "citations": [citation],
                    "manual_checklist": ["Verify"],
                }
            ),
            "instagram_empty_hashtag",
        ),
        (
            "x",
            lambda citation: XVariantPayload.model_validate(
                {
                    "mode": "single",
                    "posts": [
                        {"order": 1, "text": "First", "media": [], "citations": [citation]},
                        {"order": 2, "text": "Second", "media": [], "citations": [citation]},
                    ],
                    "link_strategy": "no_link",
                    "manual_checklist": ["Verify"],
                }
            ),
            "x_single_requires_one_post",
        ),
        (
            "blog",
            lambda citation: BlogVariantPayload.model_validate(
                {
                    "title": "Grounded article",
                    "slug": "grounded-article",
                    "excerpt": "Grounded excerpt",
                    "body_markdown": "Grounded evidence. " * 20,
                    "headings": ["Grounded"],
                    "citations": [citation],
                    "tags": [],
                    "seo_description": "Grounded evidence summary for manual publication review.",
                    "hero_media": None,
                    "canonical_sources": [],
                    "manual_checklist": ["Verify"],
                }
            ),
            "blog_canonical_sources_mismatch",
        ),
    ],
)
@pytest.mark.asyncio
async def test_manual_edit_rejects_deterministic_platform_errors_without_creating_child(
    platform,
    payload_factory,
    expected_code,
):
    _payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    variant.platform = platform
    payload = payload_factory(citation.model_dump(mode="json"))
    session = _Session(
        scalar_values=[variant, parent],
        objects={(ContentPack, pack.id): pack, (StoryRevision, story_revision.id): story_revision},
        snapshots=[snapshot],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).edit_manual_platform_variant(
            variant.id,
            _edit_request(parent, payload, citation, platform=platform),
        )

    assert caught.value.code == expected_code
    assert session.added == []


@pytest.mark.asyncio
async def test_manual_edit_rejects_stale_base_platform_conflict_and_mismatched_evidence_without_child():
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    stale = _Session(scalar_values=[variant, parent], objects={}, snapshots=[])
    stale_request = _edit_request(parent, payload, citation).model_copy(update={"base_content_hash": "c" * 64})
    with pytest.raises(RevisionConflict, match="stale"):
        await EditorialService(stale).edit_manual_platform_variant(variant.id, stale_request)
    assert stale.added == []

    conflicting_variant = PlatformVariant(
        id=variant.id,
        content_pack_id=variant.content_pack_id,
        platform="blog",
    )
    conflict = _Session(scalar_values=[conflicting_variant], objects={}, snapshots=[])
    with pytest.raises(RevisionConflict, match="platform"):
        await EditorialService(conflict).edit_manual_platform_variant(
            variant.id,
            _edit_request(parent, payload, citation),
        )
    assert conflict.added == []

    mismatch = _Session(scalar_values=[variant, parent], objects={}, snapshots=[])
    altered = citation.model_copy(update={"excerpt_sha256": "f" * 64})
    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(mismatch).edit_manual_platform_variant(
            variant.id,
            _edit_request(parent, payload, citation, evidence=[altered.model_dump(mode="json")]),
        )
    assert caught.value.code == "citation_integrity"
    assert mismatch.added == []


@pytest.mark.asyncio
async def test_approval_revalidates_stored_manual_citations_before_state_transition():
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    parent.approval_state = "pending_review"
    parent.evidence_map = [citation.model_copy(update={"excerpt_sha256": "f" * 64}).model_dump(mode="json")]
    parent.content_hash = sha256_canonical({"content": parent.content, "evidence_map": parent.evidence_map})
    session = _Session(
        scalar_values=[parent],
        objects={
            (PlatformVariant, variant.id): variant,
            (ContentPack, pack.id): pack,
            (StoryRevision, story_revision.id): story_revision,
        },
        snapshots=[snapshot],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            parent.id,
            ApprovalRequest(expected_content_hash=parent.content_hash),
        )

    assert caught.value.code == "citation_integrity"
    assert parent.approval_state == "pending_review"


def _payload_with_media(payload, media_asset_id):
    raw = payload.model_dump(mode="json")
    raw["carousel"] = [
        {
            "order": 1,
            "headline": "Grounded",
            "body": "Grounded",
            "media": {
                "media_asset_id": str(media_asset_id),
                "role": "slide",
                "order": 1,
                "alt_text": "Grounded image",
                "manual_brief": None,
                "image_prompt": None,
            },
        }
    ]
    return InstagramVariantPayload.model_validate(raw)


@pytest.mark.asyncio
async def test_manual_edit_rejects_media_not_authorized_by_immutable_story_evidence():
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    snapshot.content_item_id = uuid4()
    assigned = _payload_with_media(payload, uuid4())
    session = _Session(
        scalar_values=[variant, parent],
        objects={(ContentPack, pack.id): pack, (StoryRevision, story_revision.id): story_revision},
        snapshots=[snapshot],
        media_links=[],
        media_assets=[],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).edit_manual_platform_variant(
            variant.id,
            _edit_request(parent, assigned, citation),
        )

    assert caught.value.code == "media_integrity"
    assert session.added == []
    [media_link_query] = session.scalar_statements[1:]
    assert media_link_query._for_update_arg is None
    assert media_link_query.get_execution_options().get("populate_existing") is True


@pytest.mark.asyncio
async def test_approval_rechecks_media_authorization_before_state_transition():
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    snapshot.content_item_id = uuid4()
    parent.approval_state = "pending_review"
    assigned = _payload_with_media(payload, uuid4())
    parent.content = assigned.model_dump(mode="json")
    parent.evidence_map = [citation.model_dump(mode="json")]
    parent.content_hash = sha256_canonical({"content": parent.content, "evidence_map": parent.evidence_map})
    session = _Session(
        scalar_values=[parent],
        objects={
            (PlatformVariant, variant.id): variant,
            (ContentPack, pack.id): pack,
            (StoryRevision, story_revision.id): story_revision,
        },
        snapshots=[snapshot],
        media_links=[],
        media_assets=[],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            parent.id,
            ApprovalRequest(expected_content_hash=parent.content_hash),
        )

    assert caught.value.code == "media_integrity"
    assert parent.approval_state == "pending_review"
    [media_link_query] = session.scalar_statements[1:]
    assert media_link_query._for_update_arg is None
    assert media_link_query.get_execution_options().get("populate_existing") is True


def _tampered_citation(citation, field):
    raw = citation.model_dump(mode="json")
    raw[field] = {
        "evidence_snapshot_id": str(uuid4()),
        "evidence_key": "evidence:fabricated",
        "source_url": "https://fabricated.example/report",
        "locator": "chars:1-8",
        "excerpt_sha256": "f" * 64,
    }[field]
    return CitationRef.model_validate(raw)


@pytest.mark.parametrize(
    "field",
    ["evidence_snapshot_id", "evidence_key", "source_url", "locator", "excerpt_sha256"],
)
@pytest.mark.asyncio
async def test_manual_edit_rejects_matching_payload_and_evidence_fabrication_against_snapshot(field):
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    tampered = _tampered_citation(citation, field)
    raw = payload.model_dump(mode="json")
    raw["citations"] = [tampered.model_dump(mode="json")]
    tampered_payload = InstagramVariantPayload.model_validate(raw)
    session = _Session(
        scalar_values=[variant, parent],
        objects={(ContentPack, pack.id): pack, (StoryRevision, story_revision.id): story_revision},
        snapshots=[snapshot],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).edit_manual_platform_variant(
            variant.id,
            _edit_request(
                parent,
                tampered_payload,
                citation,
                evidence=[tampered.model_dump(mode="json")],
            ),
        )

    assert caught.value.code == "citation_integrity"
    assert session.added == []


@pytest.mark.parametrize(
    "field",
    ["evidence_snapshot_id", "evidence_key", "source_url", "locator", "excerpt_sha256"],
)
@pytest.mark.asyncio
async def test_approval_rejects_matching_content_and_evidence_fabrication_against_snapshot(field):
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    tampered = _tampered_citation(citation, field)
    raw = payload.model_dump(mode="json")
    raw["citations"] = [tampered.model_dump(mode="json")]
    parent.content = InstagramVariantPayload.model_validate(raw).model_dump(mode="json")
    parent.evidence_map = [tampered.model_dump(mode="json")]
    parent.content_hash = sha256_canonical({"content": parent.content, "evidence_map": parent.evidence_map})
    parent.approval_state = "pending_review"
    session = _Session(
        scalar_values=[parent],
        objects={
            (PlatformVariant, variant.id): variant,
            (ContentPack, pack.id): pack,
            (StoryRevision, story_revision.id): story_revision,
        },
        snapshots=[snapshot],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            parent.id,
            ApprovalRequest(expected_content_hash=parent.content_hash),
        )

    assert caught.value.code == "citation_integrity"
    assert parent.approval_state == "pending_review"


@pytest.mark.asyncio
async def test_approval_rejects_stored_content_hash_drift_before_transition():
    payload, citation, story_revision, pack, variant, parent, snapshot = _service_fixture()
    parent.approval_state = "pending_review"
    parent.content = {**parent.content, "caption": "Mutated after hashing"}
    session = _Session(
        scalar_values=[parent],
        objects={
            (PlatformVariant, variant.id): variant,
            (ContentPack, pack.id): pack,
            (StoryRevision, story_revision.id): story_revision,
        },
        snapshots=[snapshot],
    )

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            parent.id,
            ApprovalRequest(expected_content_hash=parent.content_hash),
        )

    assert caught.value.code == "content_integrity"
    assert parent.approval_state == "pending_review"


def _telegram_approval_fixture(*, evidence_order=(0, 1), media_policy="omit"):
    story_id, story_revision_id, pack_id, variant_id = uuid4(), uuid4(), uuid4(), uuid4()
    citations = []
    snapshots = []
    for index in range(2):
        snapshot_id = uuid4()
        evidence_text = "Evidence"
        citation = CitationRef.model_validate(
            {
                "evidence_key": f"evidence:{index}",
                "evidence_snapshot_id": str(snapshot_id),
                "source_url": f"https://example.com/{index}",
                "locator": "chars:0-8",
                "excerpt_sha256": hashlib.sha256(evidence_text.encode()).hexdigest(),
            }
        )
        citations.append(citation.model_dump(mode="json"))
        snapshots.append(
            SimpleNamespace(
                id=snapshot_id,
                story_id=story_id,
                evidence_key=citation.evidence_key,
                content_item_id=None,
                title="Evidence",
                content_text=evidence_text,
                content_sha256=hashlib.sha256(evidence_text.encode()).hexdigest(),
                source_url=str(citation.source_url),
                authors=[],
                published_at=None,
                captured_at=datetime.now(UTC),
            )
        )
    story_revision = StoryRevision(
        id=story_revision_id,
        story_id=story_id,
        revision_number=1,
        narrative="Grounded story",
        facts=[],
        disagreements=[],
        angles=[],
        citations=citations,
        created_by="generation",
    )
    pack = ContentPack(id=pack_id, story_revision_id=story_revision_id, brand_profile_id=uuid4(), status="draft")
    variant = PlatformVariant(id=variant_id, content_pack_id=pack_id, platform="telegram")
    content = TelegramVariantContent.model_validate(
        {
            "body": "Grounded Telegram copy",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": media_policy,
            "media_asset_ids": [],
            "direction": "rtl",
            "dry_run": False,
        }
    ).model_dump(mode="json")
    evidence_map = [citations[index] for index in evidence_order]
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant_id,
        parent_revision_id=None,
        generation_attempt_id=uuid4(),
        revision_number=1,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        approval_state="pending_review",
        created_by="generation",
    )
    session = _Session(
        scalar_values=[revision, revision.id],
        objects={
            (PlatformVariant, variant.id): variant,
            (ContentPack, pack.id): pack,
            (StoryRevision, story_revision.id): story_revision,
        },
        snapshots=snapshots,
    )
    return revision, session


@pytest.mark.parametrize("evidence_order", [(0,), (1, 0)])
@pytest.mark.asyncio
async def test_telegram_approval_requires_exact_ordered_locked_story_evidence(evidence_order):
    revision, session = _telegram_approval_fixture(evidence_order=evidence_order)

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            revision.id,
            ApprovalRequest(expected_content_hash=revision.content_hash),
        )

    assert caught.value.code == "citation_integrity"
    assert revision.approval_state == "pending_review"

@pytest.mark.asyncio
async def test_telegram_approval_revalidates_platform_policy_instead_of_trusting_green_gate():
    revision, session = _telegram_approval_fixture(media_policy="replace_manually")

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            revision.id,
            ApprovalRequest(expected_content_hash=revision.content_hash),
        )

    assert caught.value.code == "telegram_requires_manual_media_replacement"
    assert revision.approval_state == "pending_review"


@pytest.mark.asyncio
async def test_telegram_approval_rejects_fabricated_but_syntactically_valid_evidence():
    revision, session = _telegram_approval_fixture()
    revision.evidence_map = [
        CitationRef(
            evidence_key="evidence:fabricated",
            evidence_snapshot_id=uuid4(),
            source_url="https://fabricated.example/report",
            locator="chars:0-8",
            excerpt_sha256="f" * 64,
        ).model_dump(mode="json")
    ]
    revision.content_hash = sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})

    with pytest.raises(InvalidGenerationRequest) as caught:
        await EditorialService(session).approve_revision(
            revision.id,
            ApprovalRequest(expected_content_hash=revision.content_hash),
        )

    assert caught.value.code == "citation_integrity"
    assert revision.approval_state == "pending_review"
