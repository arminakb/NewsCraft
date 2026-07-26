import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.generation.handlers import (
    _artifact_requires_review,
    _manual_output_with_ordinary_issues,
    _platform_stage_input,
    _require_exact_active_prompt,
    _trusted_story_media,
    platform_limits_for,
    validate_payload_media_assignments,
)
from app.generation.multiplatform import (
    PLATFORM_PROMPT_PURPOSE,
    deduplicate_preserving_order,
    ordered_distinct_citations,
    payload_claims,
)
from app.generation.platform_renderers import render_platform_copy
from app.generation.platform_schemas import InstagramVariantPayload, TelegramVariantPayload, XVariantPayload
from app.generation.platform_validation import revision_gates_from_issues
from app.research.citations import CitationIntegrityError
from app.research.schemas import CitationRef
from app.stories.evidence import EvidenceRecord


def citation(*, snapshot_id=None, key="evidence:one", url="https://example.com/report"):
    return {
        "evidence_key": key,
        "evidence_snapshot_id": snapshot_id or uuid4(),
        "source_url": url,
        "locator": "chars:0-8",
        "excerpt_sha256": "a" * 64,
    }


def instagram_payload(*citations):
    return InstagramVariantPayload.model_validate(
        {
            "hook": "A grounded hook",
            "caption": "A grounded caption",
            "cta": "Read the source",
            "hashtags": ["#news"],
            "alt_text": "A text-only summary card",
            "carousel": [],
            "citations": list(citations),
            "manual_checklist": ["Verify the caption"],
        }
    )


def test_platform_order_is_server_resolved_and_deduplicated():
    assert deduplicate_preserving_order(["telegram", "instagram", "telegram", "blog"]) == [
        "telegram",
        "instagram",
        "blog",
    ]
    assert PLATFORM_PROMPT_PURPOSE == {
        "telegram": "telegram_pack",
        "instagram": "instagram_pack",
        "x": "x_pack",
        "blog": "blog_pack",
    }


def test_manual_payload_claims_and_evidence_map_preserve_exact_citation_order():
    first_id, second_id = uuid4(), uuid4()
    first = citation(snapshot_id=first_id)
    duplicate = dict(first)
    second = citation(snapshot_id=second_id, key="evidence:two", url=None)
    payload = instagram_payload(first, duplicate, second)

    claims = payload_claims("instagram", payload)
    evidence_map = ordered_distinct_citations(payload)

    assert len(claims) == 1
    assert claims[0].text == "A grounded hook\nA grounded caption"
    assert [item.evidence_snapshot_id for item in evidence_map] == [first_id, second_id]


def test_telegram_renderer_preserves_exact_release_two_mapping():
    stored = {
        "body": "<strong>Grounded update</strong>",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }
    payload = TelegramVariantPayload.model_validate(stored)

    assert render_platform_copy("telegram", payload) == stored["body"]


def test_x_renderer_numbers_multi_post_threads_and_keeps_single_post_plain():
    citation_value = citation()
    thread = XVariantPayload.model_validate(
        {
            "mode": "thread",
            "posts": [
                {"order": 2, "text": "Second post", "media": [], "citations": [citation_value]},
                {"order": 1, "text": "First post", "media": [], "citations": [citation_value]},
            ],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify copy"],
        }
    )
    single = XVariantPayload.model_validate(
        {
            "mode": "single",
            "posts": [{"order": 1, "text": "Only post", "media": [], "citations": [citation_value]}],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify copy"],
        }
    )

    assert render_platform_copy("x", thread) == "1/2 First post\n\n2/2 Second post"
    assert render_platform_copy("x", single) == "Only post"


def _complete_outputs(citation_value):
    return [
        {"body": "Grounded Telegram", "parse_mode": "HTML", "buttons": []},
        {
            "hook": "Grounded hook",
            "caption": "Grounded caption",
            "cta": "Read more",
            "hashtags": [],
            "alt_text": "Summary card",
            "carousel": [],
            "citations": [citation_value],
            "manual_checklist": ["Verify copy"],
        },
        {
            "mode": "single",
            "posts": [{"order": 1, "text": "Grounded post", "media": [], "citations": [citation_value]}],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify copy"],
        },
        {
            "title": "Grounded article",
            "slug": "grounded-article",
            "excerpt": "A grounded article summary.",
            "body_markdown": "Grounded evidence. " * 20,
            "headings": ["Evidence"],
            "citations": [citation_value],
            "tags": ["news"],
            "seo_description": "A grounded description of the evidence for manual publication.",
            "hero_media": None,
            "canonical_sources": [citation_value["source_url"]],
            "manual_checklist": ["Verify links"],
        },
    ]


def test_ordinary_invalid_platform_output_is_persistable_as_failed_review_gate():
    raw = _complete_outputs(citation())[1]
    raw["caption"] = "x" * 2_201

    payload, issues = _manual_output_with_ordinary_issues("instagram", raw)
    gates = revision_gates_from_issues(issues)

    assert len(payload.caption) == 2_201
    assert issues[0].code == "instagram_caption_too_long"
    assert gates[0] == {
        "gate": "instagram_caption_too_long",
        "ok": False,
        "reason": issues[0].message,
    }


def _set_instagram_slide_limit(raw, field, value):
    raw["carousel"] = [
        {
            "order": 1,
            "headline": "Grounded",
            "body": "Grounded",
            "media": {
                "media_asset_id": None,
                "role": "slide",
                "order": 1,
                "alt_text": "Grounded",
                "manual_brief": None,
                "image_prompt": None,
            },
        }
    ]
    raw["carousel"][0][field] = value


def _set_nested_media_limit(raw, platform, field, value):
    assignment = {
        "media_asset_id": None,
        "role": {"instagram": "slide", "x": "post", "blog": "hero"}[platform],
        "order": 1,
        "alt_text": "Grounded",
        "manual_brief": None,
        "image_prompt": None,
    }
    assignment[field] = value
    if platform == "instagram":
        raw["carousel"] = [{"order": 1, "headline": "Grounded", "body": "Grounded", "media": assignment}]
    elif platform == "x":
        raw["posts"][0]["media"] = [assignment]
    else:
        raw["hero_media"] = assignment


@pytest.mark.parametrize(
    ("platform", "mutate", "expected_code"),
    [
        ("instagram", lambda raw: raw.update(hook="x" * 181), "instagram_hook_too_long"),
        ("instagram", lambda raw: raw.update(caption="x" * 2_201), "instagram_caption_too_long"),
        ("instagram", lambda raw: raw.update(cta="x" * 301), "instagram_cta_too_long"),
        ("instagram", lambda raw: raw.update(alt_text="x" * 1_001), "instagram_alt_text_too_long"),
        ("instagram", lambda raw: raw.update(hashtags=[f"#tag{i}" for i in range(31)]), "instagram_too_many_hashtags"),
        (
            "instagram",
            lambda raw: raw.update(
                carousel=[
                    {
                        "order": index,
                        "headline": f"Slide {index}",
                        "body": "Grounded",
                        "media": {
                            "media_asset_id": None,
                            "role": "slide",
                            "order": index,
                            "alt_text": "Grounded slide",
                            "manual_brief": "Create manually",
                            "image_prompt": None,
                        },
                    }
                    for index in range(1, 22)
                ]
            ),
            "instagram_carousel_too_long",
        ),
        (
            "instagram",
            lambda raw: _set_instagram_slide_limit(raw, "headline", "x" * 121),
            "instagram_slide_headline_too_long",
        ),
        (
            "instagram",
            lambda raw: _set_instagram_slide_limit(raw, "body", "x" * 501),
            "instagram_slide_body_too_long",
        ),
        (
            "instagram",
            lambda raw: _set_instagram_slide_limit(raw, "order", 21),
            "instagram_carousel_order_invalid",
        ),
        (
            "instagram",
            lambda raw: _set_nested_media_limit(raw, "instagram", "alt_text", "x" * 1_001),
            "instagram_media_alt_text_too_long",
        ),
        (
            "instagram",
            lambda raw: _set_nested_media_limit(raw, "instagram", "manual_brief", "x" * 2_001),
            "instagram_media_manual_brief_too_long",
        ),
        (
            "instagram",
            lambda raw: _set_nested_media_limit(raw, "instagram", "image_prompt", "x" * 2_001),
            "instagram_media_image_prompt_too_long",
        ),
        (
            "x",
            lambda raw: raw.update(
                mode="thread",
                posts=[
                    {
                        "order": index,
                        "text": f"Grounded post {index}",
                        "media": [],
                        "citations": raw["posts"][0]["citations"],
                    }
                    for index in range(1, 27)
                ],
            ),
            "x_too_many_posts",
        ),
        (
            "x",
            lambda raw: raw["posts"][0].update(
                media=[
                    {
                        "media_asset_id": None,
                        "role": "post",
                        "order": index,
                        "alt_text": f"Media {index}",
                        "manual_brief": "Create manually",
                        "image_prompt": None,
                    }
                    for index in range(1, 6)
                ]
            ),
            "x_too_many_media",
        ),
        ("x", lambda raw: raw["posts"][0].update(order=26), "x_post_order_invalid"),
        (
            "x",
            lambda raw: _set_nested_media_limit(raw, "x", "alt_text", "x" * 1_001),
            "x_media_alt_text_too_long",
        ),
        (
            "x",
            lambda raw: _set_nested_media_limit(raw, "x", "manual_brief", "x" * 2_001),
            "x_media_manual_brief_too_long",
        ),
        (
            "x",
            lambda raw: _set_nested_media_limit(raw, "x", "image_prompt", "x" * 2_001),
            "x_media_image_prompt_too_long",
        ),
        ("blog", lambda raw: raw.update(title="x" * 121), "blog_title_too_long"),
        ("blog", lambda raw: raw.update(slug="x" * 121), "blog_slug_too_long"),
        ("blog", lambda raw: raw.update(excerpt="x" * 301), "blog_excerpt_too_long"),
        ("blog", lambda raw: raw.update(tags=[f"tag-{index}" for index in range(21)]), "blog_too_many_tags"),
        ("blog", lambda raw: raw.update(seo_description="x" * 161), "blog_seo_description_too_long"),
        (
            "blog",
            lambda raw: _set_nested_media_limit(raw, "blog", "alt_text", "x" * 1_001),
            "blog_media_alt_text_too_long",
        ),
        (
            "blog",
            lambda raw: _set_nested_media_limit(raw, "blog", "manual_brief", "x" * 2_001),
            "blog_media_manual_brief_too_long",
        ),
        (
            "blog",
            lambda raw: _set_nested_media_limit(raw, "blog", "image_prompt", "x" * 2_001),
            "blog_media_image_prompt_too_long",
        ),
    ],
)
def test_every_validator_backed_schema_max_is_preserved_as_reviewable_issue(platform, mutate, expected_code):
    index = {"instagram": 1, "x": 2, "blog": 3}[platform]
    raw = _complete_outputs(citation())[index]
    mutate(raw)

    payload, issues = _manual_output_with_ordinary_issues(platform, raw)

    assert expected_code in {issue.code for issue in issues}
    assert any(not gate["ok"] for gate in revision_gates_from_issues(issues))
    assert payload.model_dump(mode="json") == __import__("pydantic_core").to_jsonable_python(raw)


@pytest.mark.parametrize(
    ("platform", "mutate", "expected_code"),
    [
        ("instagram", lambda raw: raw.update(hook=""), "instagram_hook_empty"),
        ("x", lambda raw: raw.update(posts=[]), "x_posts_missing"),
        ("blog", lambda raw: raw.update(body_markdown="short"), "blog_body_too_short"),
        ("blog", lambda raw: raw.update(headings=[]), "blog_headings_missing"),
        ("blog", lambda raw: raw.update(seo_description="short"), "blog_seo_description_too_short"),
    ],
)
def test_operational_minimums_are_deferred_to_reviewable_validation(platform, mutate, expected_code):
    index = {"instagram": 1, "x": 2, "blog": 3}[platform]
    raw = _complete_outputs(citation())[index]
    mutate(raw)

    payload, issues = _manual_output_with_ordinary_issues(platform, raw)

    assert expected_code in {issue.code for issue in issues}
    assert payload.model_dump(mode="json") == __import__("pydantic_core").to_jsonable_python(raw)


@pytest.mark.parametrize(
    ("platform", "mutate"),
    [
        ("instagram", lambda raw: raw.update(hook=123)),
        ("instagram", lambda raw: raw.pop("cta")),
        ("blog", lambda raw: raw.update(slug="Invalid Slug")),
        ("x", lambda raw: raw["posts"][0].update(citations=[])),
    ],
)
def test_wrong_type_missing_pattern_and_empty_citation_integrity_remain_strict(platform, mutate):
    index = {"instagram": 1, "x": 2, "blog": 3}[platform]
    raw = _complete_outputs(citation())[index]
    mutate(raw)

    with pytest.raises((ValidationError, ValueError)):
        _manual_output_with_ordinary_issues(platform, raw)


def test_telegram_trusted_assembly_preserves_locked_parent_context_and_ignores_provider_provenance():
    from app.generation.telegram_schema import (
        TelegramRewriteOutput,
        TelegramVariantContent,
        assemble_telegram_variant,
    )

    source_item_id, media_asset_id = uuid4(), uuid4()
    parent = TelegramVariantContent.model_validate(
        {
            "body": "Old",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": str(source_item_id),
            "source_url": "https://example.com/locked",
            "media_policy": "replace_manually",
            "media_asset_ids": [str(media_asset_id)],
            "direction": "ltr",
            "dry_run": True,
        }
    )
    authored = TelegramRewriteOutput(body="New provider copy", parse_mode="HTML", buttons=[])

    regenerated = assemble_telegram_variant(authored, trusted_parent=parent, default_direction="rtl")
    initial = assemble_telegram_variant(authored, trusted_parent=None, default_direction="rtl")

    assert regenerated.model_dump(mode="json") == {
        "body": "New provider copy",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": str(source_item_id),
        "source_url": "https://example.com/locked",
        "media_policy": "replace_manually",
        "media_asset_ids": [str(media_asset_id)],
        "direction": "ltr",
        "dry_run": True,
    }
    assert initial.model_dump(mode="json") == {
        "body": "New provider copy",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }


@pytest.mark.asyncio
async def test_telegram_artifact_replay_reconstructs_expected_content_from_immutable_parent():
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.handlers import _artifact_requires_review
    from app.generation.telegram_schema import TelegramRewriteOutput, assemble_telegram_variant

    fixture = _pack_handler_fixture(platforms=("telegram",))
    pack_id, variant_id, parent_id, revision_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    source_item_id, media_asset_id = uuid4(), uuid4()
    parent_content = {
        "body": "Old",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": str(source_item_id),
        "source_url": "https://example.com/locked",
        "media_policy": "preserve",
        "media_asset_ids": [str(media_asset_id)],
        "direction": "ltr",
        "dry_run": True,
    }
    authored = TelegramRewriteOutput(body="Replayed provider copy", parse_mode="HTML", buttons=[])
    content = assemble_telegram_variant(
        authored,
        trusted_parent=parent_content,
        default_direction="rtl",
    ).model_dump(mode="json")
    evidence_map = [fixture.ref.model_dump(mode="json")]
    gates = [{"gate": "platform_schema", "ok": True, "reason": None}]
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=fixture.story_revision.id,
        brand_profile_id=fixture.brand.id,
    )
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="telegram")
    parent = SimpleNamespace(
        id=parent_id,
        platform_variant_id=variant_id,
        content=parent_content,
    )
    revision = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        parent_revision_id=parent_id,
        generation_attempt_id=attempt_id,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=gates,
    )
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[],
        scalar_values=[pack, variant, revision, parent],
    )

    requires_review = await _artifact_requires_review(
        session,
        {
            "content_pack_id": str(pack_id),
            "variant_id": str(variant_id),
            "revision_id": str(revision_id),
            "platform": "telegram",
        },
        expected_platform="telegram",
        expected_story_revision_id=fixture.story_revision.id,
        expected_brand_profile_id=fixture.brand.id,
        expected_attempt_id=attempt_id,
        authored=authored,
        expected_content=None,
        expected_evidence_map=evidence_map,
        expected_validation_results=gates,
        evidence=fixture.evidence,
        telegram_default_direction="rtl",
    )

    assert requires_review is False


def test_generation_input_uses_concrete_per_platform_limits():
    assert {
        "caption_max": 2200,
        "hashtag_max": 30,
        "carousel_max": 20,
    }.items() <= platform_limits_for("instagram").items()
    assert {
        "post_weight_max": 280,
        "posts_max": 25,
        "media_per_post_max": 4,
        "url_weight": 23,
    }.items() <= platform_limits_for("x").items()
    assert platform_limits_for("blog")["seo_description_max"] == 160


@pytest.mark.asyncio
async def test_source_media_is_grounded_to_story_evidence_and_provider_projection_is_safe():
    from app.db.models import MediaAsset

    content_item_id, asset_id, invalid_asset_id, snapshot_id = uuid4(), uuid4(), uuid4(), uuid4()
    evidence = {
        snapshot_id: EvidenceRecord(
            evidence_key="evidence:one",
            evidence_snapshot_id=snapshot_id,
            content_item_id=content_item_id,
            title="Evidence",
            content_text="Evidence",
            content_sha256="a" * 64,
            source_url=None,
            authors=(),
            published_at=None,
            captured_at=datetime.now(UTC),
        )
    }
    link = SimpleNamespace(content_item_id=content_item_id, media_asset_id=asset_id, role="hero", sort_order=1)
    duplicate_link = SimpleNamespace(
        content_item_id=content_item_id,
        media_asset_id=asset_id,
        role="inline",
        sort_order=2,
    )
    invalid_link = SimpleNamespace(
        content_item_id=content_item_id,
        media_asset_id=invalid_asset_id,
        role="inline",
        sort_order=3,
    )
    asset = SimpleNamespace(
        id=asset_id,
        original_url="https://secret.example/media.jpg",
        storage_path="/data/media/secret.jpg",
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=800,
        duration_seconds=None,
        byte_length=1234,
        checksum_sha256="b" * 64,
        fetch_status="downloaded",
    )
    invalid_asset = SimpleNamespace(
        id=invalid_asset_id,
        original_url="https://secret.example/pending.jpg",
        storage_path=None,
        kind="image",
        mime_type="image/jpeg",
        width=None,
        height=None,
        duration_seconds=None,
        byte_length=None,
        checksum_sha256=None,
        fetch_status="pending",
    )

    class Session:
        def __init__(self):
            self.calls = 0
            self.statements = []

        async def scalars(self, statement):
            self.calls += 1
            self.statements.append(statement)
            return [link, duplicate_link, invalid_link] if self.calls == 1 else [invalid_asset, asset]

    authorized, projection = await _trusted_story_media(Session(), evidence)

    assert set(authorized) == {asset_id}
    assert projection == [
        {
            "id": str(asset_id),
            "kind": "image",
            "mime_type": "image/jpeg",
            "width": 1200,
            "height": 800,
            "duration_seconds": None,
            "byte_length": 1234,
            "checksum_sha256": "b" * 64,
            "fetch_status": "downloaded",
            "available": True,
            "role": "hero",
            "order": 1,
        },
        {
            "id": str(invalid_asset_id),
            "kind": "image",
            "mime_type": "image/jpeg",
            "width": None,
            "height": None,
            "duration_seconds": None,
            "byte_length": None,
            "checksum_sha256": None,
            "fetch_status": "pending",
            "available": False,
            "role": "inline",
            "order": 3,
        },
    ]
    assert all("storage_path" not in item and "original_url" not in item for item in projection)

    locked_session = Session()
    await _trusted_story_media(locked_session, evidence, lock_rows=True)
    assert len(locked_session.statements) == 2
    link_statement, asset_statement = locked_session.statements
    assert link_statement._for_update_arg is None
    assert asset_statement._for_update_arg is not None
    assert asset_statement.get_execution_options().get("populate_existing") is True
    assert len(asset_statement._order_by_clauses) == 1
    assert asset_statement._order_by_clauses[0].compare(MediaAsset.__table__.c.id)


def test_platform_stage_input_hash_binds_concrete_limits_and_safe_source_media():
    profile_id = uuid4()
    media = [
        {
            "id": str(uuid4()),
            "kind": "image",
            "mime_type": "image/jpeg",
            "width": 1200,
            "height": 800,
            "duration_seconds": None,
            "byte_length": 1234,
            "checksum_sha256": "b" * 64,
            "fetch_status": "downloaded",
            "available": True,
            "role": "hero",
            "order": 1,
        }
    ]
    input_payload, stage_hash = _platform_stage_input(
        platform="instagram",
        canonical_story={"narrative": "Grounded"},
        brand_profile={"output_language": "fa", "platform_preferences": {}},
        prompt_checksum="c" * 64,
        provider_profile_id=profile_id,
        instruction="Use a concise hook",
        source_media=media,
    )

    assert __import__("json").loads(input_payload["platform_limits_json"])["caption_max"] == 2200
    assert __import__("json").loads(input_payload["source_media_json"]) == media
    assert input_payload["direction"] == "rtl"
    changed_media = [{**media[0], "checksum_sha256": "d" * 64}]
    _, changed_hash = _platform_stage_input(
        platform="instagram",
        canonical_story={"narrative": "Grounded"},
        brand_profile={"output_language": "fa", "platform_preferences": {}},
        prompt_checksum="c" * 64,
        provider_profile_id=profile_id,
        instruction="Use a concise hook",
        source_media=changed_media,
    )
    assert stage_hash != changed_hash


def test_non_null_media_assignment_must_be_authorized_downloaded_and_verified():
    asset_id = uuid4()
    raw = _complete_outputs(citation())[1]
    raw["carousel"] = [
        {
            "order": 1,
            "headline": "Grounded",
            "body": "Grounded",
            "media": {
                "media_asset_id": str(asset_id),
                "role": "slide",
                "order": 1,
                "alt_text": "Grounded",
                "manual_brief": None,
                "image_prompt": None,
            },
        }
    ]
    payload = InstagramVariantPayload.model_validate(raw)
    valid = SimpleNamespace(
        id=asset_id,
        fetch_status="downloaded",
        storage_path="/data/media/a.jpg",
        checksum_sha256="a" * 64,
    )

    validate_payload_media_assignments(payload, {asset_id: valid})
    with pytest.raises(CitationIntegrityError):
        validate_payload_media_assignments(payload, {})
    with pytest.raises(CitationIntegrityError):
        validate_payload_media_assignments(
            payload,
            {asset_id: SimpleNamespace(id=asset_id, fetch_status="pending", storage_path=None, checksum_sha256=None)},
        )


def test_null_media_assignment_with_manual_brief_is_allowed():
    raw = _complete_outputs(citation())[1]
    raw["carousel"] = [
        {
            "order": 1,
            "headline": "Grounded",
            "body": "Grounded",
            "media": {
                "media_asset_id": None,
                "role": "slide",
                "order": 1,
                "alt_text": "Grounded",
                "manual_brief": "Create a source-grounded card manually",
                "image_prompt": None,
            },
        }
    ]
    validate_payload_media_assignments(InstagramVariantPayload.model_validate(raw), {})


def test_null_media_assignment_rejects_whitespace_only_brief_and_prompt():
    raw = _complete_outputs(citation())[1]
    raw["carousel"] = [
        {
            "order": 1,
            "headline": "Grounded",
            "body": "Grounded",
            "media": {
                "media_asset_id": None,
                "role": "slide",
                "order": 1,
                "alt_text": "Grounded",
                "manual_brief": "   ",
                "image_prompt": "\t",
            },
        }
    ]

    with pytest.raises(CitationIntegrityError):
        validate_payload_media_assignments(InstagramVariantPayload.model_validate(raw), {})


@pytest.mark.asyncio
async def test_retry_checkpoint_reloads_failed_revision_gates_and_remains_needs_review():
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError

    content_text = "Evidence"
    snapshot_id = uuid4()
    citation_value = citation(snapshot_id=snapshot_id)
    citation_value["excerpt_sha256"] = hashlib.sha256(content_text.encode()).hexdigest()
    raw = _complete_outputs(citation_value)[1]
    raw["caption"] = "x" * 2_201
    authored, issues = _manual_output_with_ordinary_issues("instagram", raw)
    content = authored.model_dump(mode="json")
    evidence_map = [item.model_dump(mode="json") for item in ordered_distinct_citations(authored)]
    expected_validation_results = revision_gates_from_issues(issues)
    evidence = {
        snapshot_id: EvidenceRecord(
            evidence_key=citation_value["evidence_key"],
            evidence_snapshot_id=snapshot_id,
            content_item_id=None,
            title="Evidence",
            content_text=content_text,
            content_sha256=hashlib.sha256(content_text.encode()).hexdigest(),
            source_url=citation_value["source_url"],
            authors=(),
            published_at=None,
            captured_at=datetime.now(UTC),
        )
    }
    pack_id, variant_id, revision_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    revision = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        generation_attempt_id=attempt_id,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=expected_validation_results,
    )
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="instagram")
    story_revision_id, brand_profile_id = uuid4(), uuid4()
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=story_revision_id,
        brand_profile_id=brand_profile_id,
    )

    statements = []

    class Session:
        async def scalar(self, statement):
            statements.append(statement)
            entity = statement.column_descriptions[0]["entity"]
            return {
                ContentPack: pack,
                PlatformVariant: variant,
                PlatformVariantRevision: revision,
            }.get(entity)

    artifact = {
        "content_pack_id": str(pack_id),
        "variant_id": str(variant_id),
        "revision_id": str(revision_id),
        "platform": "instagram",
    }
    assert (
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
        is True
    )
    pack_query, variant_query, revision_query = statements
    assert pack_query._for_update_arg is None
    assert variant_query._for_update_arg is not None
    assert revision_query._for_update_arg is not None
    assert all(statement.get_execution_options().get("populate_existing") is True for statement in statements)
    statements.clear()
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            {**artifact, "content_pack_id": str(uuid4())},
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=uuid4(),
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
    revision.generation_attempt_id = uuid4()
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
    revision.generation_attempt_id = attempt_id
    revision.content_hash = "0" * 64
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
    drifted_evidence = [{**evidence_map[0], "excerpt_sha256": "f" * 64}]
    revision.evidence_map = drifted_evidence
    revision.content_hash = sha256_canonical({"content": revision.content, "evidence_map": drifted_evidence})
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
    revision.evidence_map = evidence_map
    revision.content_hash = sha256_canonical({"content": revision.content, "evidence_map": evidence_map})
    revision.validation_results = [{"gate": "tampered", "ok": True, "reason": None}]
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )
    revision.validation_results = [{"gate": "invalid", "ok": "false", "reason": None}]
    with pytest.raises(NeedsReviewJobError):
        await _artifact_requires_review(
            Session(),
            artifact,
            expected_platform="instagram",
            expected_story_revision_id=story_revision_id,
            expected_brand_profile_id=brand_profile_id,
            expected_attempt_id=attempt_id,
            authored=authored,
            expected_content=content,
            expected_evidence_map=evidence_map,
            expected_validation_results=expected_validation_results,
            evidence=evidence,
        )


@pytest.mark.asyncio
async def test_prompt_drift_before_later_platform_is_permanent_and_never_dispatches_provider():
    from app.jobs.errors import PermanentJobError

    requested_id = uuid4()
    replacement = SimpleNamespace(id=uuid4())
    calls = 0

    class Session:
        async def scalars(self, statement):
            return [replacement]

    class Provider:
        async def generate(self, request):
            nonlocal calls
            calls += 1

    with pytest.raises(PermanentJobError) as caught:
        await _require_exact_active_prompt(Session(), "instagram", requested_id, "a" * 64)

    assert caught.value.code == "generation_platform_prompt_configuration_invalid"
    assert calls == 0


@pytest.mark.asyncio
async def test_prompt_checksum_drift_before_provider_is_permanent():
    from app.jobs.errors import PermanentJobError

    requested_id = uuid4()
    active = SimpleNamespace(id=requested_id, checksum_sha256="b" * 64)

    class Session:
        async def scalars(self, statement):
            return [active]

    with pytest.raises(PermanentJobError) as caught:
        await _require_exact_active_prompt(Session(), "instagram", requested_id, "a" * 64)

    assert caught.value.code == "generation_platform_prompt_configuration_invalid"


@pytest.mark.asyncio
async def test_all_selected_prompts_lock_in_canonical_order_before_first_provider(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PromptTemplateVersion
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext

    class PromptOrderSession(_PackHandlerSession):
        async def scalars(self, statement):
            if statement.column_descriptions[0].get("entity") is PromptTemplateVersion:
                assert statement._for_update_arg is not None
            return await super().scalars(statement)

    fixture = _pack_handler_fixture(platforms=("blog", "instagram"))
    session = PromptOrderSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"], fixture.prompts["blog"]],
        scalar_values=[fixture.story],
    )
    checked = []
    provider_calls = 0

    def require_integrity(prompt):
        checked.append(prompt.id)
        if prompt.id == fixture.prompts["blog"].id:
            raise ValueError("corrupt later prompt")

    async def invoke(context, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not run before every prompt passes preflight")

    monkeypatch.setattr("app.generation.handlers.require_prompt_integrity", require_integrity)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(PermanentJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    assert caught.value.code == "generation_prompt_integrity_failed"
    assert checked == [fixture.prompts["instagram"].id, fixture.prompts["blog"].id]
    assert provider_calls == 0


class _PackHandlerSession:
    def __init__(self, *, story_revision, brand, prompts, scalar_values, objects=None):
        self.story_revision = story_revision
        self.brand = brand
        self.prompts = list(prompts)
        self.scalar_values = list(scalar_values)
        self.objects = dict(objects or {})
        self.added = []
        self.commits = 0

    async def get(self, model, identifier):
        from app.generation.models import BrandProfile
        from app.stories.models import StoryRevision

        if model is StoryRevision and identifier == self.story_revision.id:
            return self.story_revision
        if model is BrandProfile and identifier == self.brand.id:
            return self.brand
        return self.objects.get((model, identifier))

    async def scalar(self, statement):
        return self.scalar_values.pop(0)

    async def scalars(self, statement):
        from app.jobs.models import WorkflowJob

        if statement.column_descriptions[0].get("entity") is WorkflowJob:
            return []
        return [self.prompts.pop(0)]

    def add(self, value):
        self.added.append(value)
        identifier = getattr(value, "id", None)
        if identifier is not None:
            self.objects[(type(value), identifier)] = value

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


async def _resolved(value):
    return value


def _pack_handler_fixture(*, platforms=("instagram",), media_asset_id=None):
    from app.generation.default_prompts import prompt_checksum

    content = "Evidence"
    snapshot_id = uuid4()
    citation_value = citation(snapshot_id=snapshot_id)
    citation_value["excerpt_sha256"] = hashlib.sha256(content.encode()).hexdigest()
    ref = CitationRef.model_validate(citation_value)
    evidence = {
        snapshot_id: EvidenceRecord(
            evidence_key=ref.evidence_key,
            evidence_snapshot_id=snapshot_id,
            content_item_id=uuid4(),
            title="Evidence",
            content_text=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            source_url=str(ref.source_url),
            authors=(),
            published_at=None,
            captured_at=datetime.now(UTC),
        )
    }
    story_id, revision_id, brand_id, profile_id = uuid4(), uuid4(), uuid4(), uuid4()
    story_revision = SimpleNamespace(
        id=revision_id,
        story_id=story_id,
        narrative="Grounded story",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[ref.model_dump(mode="json")],
    )
    story = SimpleNamespace(id=story_id, superseded_by_id=None, status="inbox")
    brand = SimpleNamespace(
        id=brand_id,
        name="Newsroom",
        output_language="fa",
        tone="neutral",
        editorial_rules=[],
        attribution_rules={},
        default_hashtags=[],
        platform_preferences={"instagram": {"direction": "rtl"}},
    )
    prompts = {}
    for platform in platforms:
        system_template = f"Grounded {platform} system"
        user_template = "Input={canonical_story_json}"
        output_schema = {}
        prompts[platform] = SimpleNamespace(
            id=uuid4(),
            system_template=system_template,
            user_template=user_template,
            output_schema=output_schema,
            checksum_sha256=prompt_checksum(system_template, user_template, output_schema),
        )
    raw = _complete_outputs(citation_value)[1]
    if media_asset_id is not None:
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
    job = SimpleNamespace(
        id=uuid4(),
        attempt_count=1,
        result={},
        payload={
            "story_revision_id": str(revision_id),
            "brand_profile_id": str(brand_id),
            "generation_provider_profile_id": str(profile_id),
            "platforms": list(platforms),
            "platform_prompt_template_version_ids": {platform: str(prompt.id) for platform, prompt in prompts.items()},
            "platform_prompt_checksums": {platform: prompt.checksum_sha256 for platform, prompt in prompts.items()},
        },
    )
    return SimpleNamespace(
        ref=ref,
        evidence=evidence,
        story_revision=story_revision,
        story=story,
        brand=brand,
        profile_id=profile_id,
        prompts=prompts,
        raw=raw,
        job=job,
    )


@pytest.mark.asyncio
async def test_pack_handler_wires_safe_media_limits_hash_and_prompt_recheck_before_provider(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PlatformVariantRevision
    from app.jobs.registry import JobContext

    media_asset_id = uuid4()
    fixture = _pack_handler_fixture(media_asset_id=media_asset_id)
    safe_media = [
        {
            "id": str(media_asset_id),
            "kind": "image",
            "mime_type": "image/jpeg",
            "width": 1200,
            "height": 800,
            "duration_seconds": None,
            "byte_length": 1234,
            "checksum_sha256": "a" * 64,
            "fetch_status": "downloaded",
            "available": True,
            "role": "hero",
            "order": 1,
        }
    ]
    asset = SimpleNamespace(
        id=media_asset_id,
        fetch_status="downloaded",
        storage_path="/data/media/grounded.jpg",
        checksum_sha256="a" * 64,
    )
    run_id, attempt_id = uuid4(), uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[fixture.story, None, fixture.story, durable_run, None, None, None, None],
    )
    rechecks = []
    invocation = {}

    async def locked_evidence(context, story_revision):
        return [fixture.ref], fixture.evidence

    async def trusted_media(session_value, evidence, **kwargs):
        return {media_asset_id: asset}, safe_media

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        rechecks.append((platform, prompt_id))
        return fixture.prompts[platform]

    async def invoke(context, **kwargs):
        invocation.update(kwargs)
        await kwargs["before_provider_call"]()
        authored = kwargs["validate_output"](fixture.raw)
        return durable_run, SimpleNamespace(id=attempt_id), authored

    monkeypatch.setattr("app.generation.handlers._locked_story_evidence", locked_evidence)
    monkeypatch.setattr("app.generation.handlers._trusted_story_media", trusted_media)
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    result = await build_pack_generation_handler(SimpleNamespace())(
        fixture.job,
        JobContext(session=session, providers=SimpleNamespace()),
    )

    assert result["platforms"] == ["instagram"]
    assert rechecks == [("instagram", fixture.prompts["instagram"].id)]
    assert __import__("json").loads(invocation["input_payload"]["platform_limits_json"])["caption_max"] == 2200
    assert __import__("json").loads(invocation["input_payload"]["source_media_json"]) == safe_media
    expected_input, expected_hash = _platform_stage_input(
        platform="instagram",
        canonical_story={
            "narrative": fixture.story_revision.narrative,
            "facts": [],
            "disagreements": [],
            "angles": [],
            "citations": fixture.story_revision.citations,
        },
        brand_profile={
            "id": str(fixture.brand.id),
            "name": fixture.brand.name,
            "output_language": fixture.brand.output_language,
            "tone": fixture.brand.tone,
            "editorial_rules": fixture.brand.editorial_rules,
            "attribution_rules": fixture.brand.attribution_rules,
            "default_hashtags": fixture.brand.default_hashtags,
            "platform_preferences": fixture.brand.platform_preferences,
        },
        prompt_checksum=fixture.prompts["instagram"].checksum_sha256,
        provider_profile_id=fixture.profile_id,
        instruction=None,
        source_media=safe_media,
    )
    assert invocation["input_payload"] == expected_input
    assert invocation["input_hash"] == expected_hash
    revisions = [item for item in session.added if isinstance(item, PlatformVariantRevision)]
    assert len(revisions) == 1


@pytest.mark.asyncio
async def test_release_three_queued_telegram_job_uses_singular_prompt_checksum_fallback(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture(platforms=("telegram",))
    fixture.raw = _complete_outputs(fixture.ref.model_dump(mode="json"))[0]
    prompt = fixture.prompts["telegram"]
    fixture.job.payload = {
        key: value
        for key, value in fixture.job.payload.items()
        if key
        not in {
            "platforms",
            "platform_prompt_template_version_ids",
            "platform_prompt_checksums",
        }
    } | {
        "platform": "telegram",
        "platform_prompt_template_version_id": str(prompt.id),
        "platform_prompt_checksum": prompt.checksum_sha256,
    }
    run_id, attempt_id = uuid4(), uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[prompt],
        scalar_values=[fixture.story, None, fixture.story, durable_run, None, None, None, None],
    )

    async def invoke(context, **kwargs):
        await kwargs["before_provider_call"]()
        return (
            SimpleNamespace(id=run_id),
            SimpleNamespace(id=attempt_id),
            kwargs["validate_output"](fixture.raw),
        )

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return prompt

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    result = await build_pack_generation_handler(SimpleNamespace())(
        fixture.job,
        JobContext(session=session, providers=SimpleNamespace()),
    )

    assert result["platforms"] == ["telegram"]
    assert len(result["revisions"]) == 1


@pytest.mark.asyncio
async def test_existing_telegram_variant_generation_preserves_exact_trusted_parent_context(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture(platforms=("telegram",))
    fixture.raw = _complete_outputs(fixture.ref.model_dump(mode="json"))[0]
    pack_id, variant_id, source_item_id, media_asset_id = uuid4(), uuid4(), uuid4(), uuid4()
    parent_content = {
        "body": "Old",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": str(source_item_id),
        "source_url": "https://example.com/locked",
        "media_policy": "replace_manually",
        "media_asset_ids": [str(media_asset_id)],
        "direction": "ltr",
        "dry_run": True,
    }
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=fixture.story_revision.id,
        brand_profile_id=fixture.brand.id,
    )
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="telegram")
    parent = SimpleNamespace(
        id=uuid4(),
        platform_variant_id=variant_id,
        revision_number=4,
        content_hash="b" * 64,
        content=parent_content,
    )
    run_id, attempt_id = uuid4(), uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["telegram"]],
        scalar_values=[
            fixture.story,
            pack.id,
            fixture.story,
            durable_run,
            pack,
            variant,
            None,
            parent,
        ],
    )

    async def invoke(context, **kwargs):
        await kwargs["before_provider_call"]()
        return (
            SimpleNamespace(id=run_id),
            SimpleNamespace(id=attempt_id),
            kwargs["validate_output"](fixture.raw),
        )

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    revision = next(item for item in session.added if isinstance(item, PlatformVariantRevision))
    assert caught.value.code == "platform_validation_failed"
    assert revision.parent_revision_id == parent.id
    assert revision.content == {
        **parent_content,
        "body": fixture.raw["body"],
        "parse_mode": fixture.raw["parse_mode"],
        "buttons": fixture.raw["buttons"],
    }
    assert revision.validation_results[0]["gate"] == "telegram_requires_manual_media_replacement"
    assert revision.validation_results[0]["ok"] is False


@pytest.mark.asyncio
async def test_pack_handler_relocks_media_after_provider_and_rejects_unlinked_assignment(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    media_asset_id = uuid4()
    fixture = _pack_handler_fixture(media_asset_id=media_asset_id)
    asset = SimpleNamespace(
        id=media_asset_id,
        fetch_status="downloaded",
        storage_path="/data/media/grounded.jpg",
        checksum_sha256="a" * 64,
    )
    run_id = uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[fixture.story, None, fixture.story, durable_run, None, None, None, None],
    )
    media_reads = []

    async def trusted_media(session_value, evidence, *, lock_rows=False):
        media_reads.append(lock_rows)
        return ({media_asset_id: asset}, []) if not lock_rows else ({}, [])

    async def invoke(context, **kwargs):
        await kwargs["before_provider_call"]()
        authored = kwargs["validate_output"](fixture.raw)
        return SimpleNamespace(id=run_id), SimpleNamespace(id=uuid4()), authored

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr("app.generation.handlers._trusted_story_media", trusted_media)
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    assert caught.value.code == "media_integrity"
    assert media_reads == [False, True]
    assert not any(isinstance(item, PlatformVariantRevision) for item in session.added)


@pytest.mark.asyncio
async def test_pack_handler_rejects_unauthorized_provider_media_before_revision(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture(media_asset_id=uuid4())
    run_id = uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[fixture.story, None, fixture.story, durable_run, None, None, None, None],
    )

    async def invoke(context, **kwargs):
        await kwargs["before_provider_call"]()
        authored = kwargs["validate_output"](fixture.raw)
        return SimpleNamespace(id=run_id), SimpleNamespace(id=uuid4()), authored

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )
    assert caught.value.code == "media_integrity"
    assert not any(isinstance(item, PlatformVariantRevision) for item in session.added)


@pytest.mark.asyncio
async def test_pack_handler_retry_uses_linked_failed_artifact_and_persists_needs_review_result(monkeypatch):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture()
    fixture.raw["caption"] = "x" * 2_201
    pack_id, variant_id, revision_id, run_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    pack = SimpleNamespace(id=pack_id, story_revision_id=fixture.story_revision.id, brand_profile_id=fixture.brand.id)
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="instagram")
    authored, issues = _manual_output_with_ordinary_issues("instagram", fixture.raw)
    content = authored.model_dump(mode="json")
    evidence_map = [item.model_dump(mode="json") for item in ordered_distinct_citations(authored)]
    revision = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        generation_attempt_id=attempt_id,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=revision_gates_from_issues(issues),
    )
    artifact = {
        "content_pack_id": str(pack_id),
        "variant_id": str(variant_id),
        "revision_id": str(revision_id),
        "platform": "instagram",
    }
    durable_run = SimpleNamespace(id=run_id, output_payload={"_artifact": artifact})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[fixture.story, None, fixture.story, durable_run, pack, variant, revision],
        objects={
            (ContentPack, pack_id): pack,
            (PlatformVariant, variant_id): variant,
            (PlatformVariantRevision, revision_id): revision,
        },
    )

    async def invoke(context, **kwargs):
        await kwargs["before_provider_call"]()
        return durable_run, SimpleNamespace(id=attempt_id), authored

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision_value: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    assert caught.value.code == "platform_validation_failed"
    assert fixture.job.result["content_pack_id"] == str(pack_id)
    assert fixture.job.result["revisions"] == [{"variant_id": str(variant_id), "revision_id": str(revision_id)}]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_pack_handler_records_incremental_result_before_later_platform_failure(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture(platforms=("instagram", "blog"))
    run_id, attempt_id = uuid4(), uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"], fixture.prompts["blog"]],
        scalar_values=[fixture.story, None, fixture.story, durable_run, None, None, None, None],
    )
    calls = 0

    async def invoke(context, **kwargs):
        nonlocal calls
        calls += 1
        await kwargs["before_provider_call"]()
        if calls == 2:
            raise NeedsReviewJobError(code="citation_integrity", message="Blog citations failed")
        authored = kwargs["validate_output"](fixture.raw)
        return SimpleNamespace(id=run_id), SimpleNamespace(id=attempt_id), authored

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision_value: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError, match="Blog citations failed"):
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    assert calls == 2
    assert fixture.job.result["content_pack_id"]
    assert fixture.job.result["platforms"] == ["instagram"]
    assert len(fixture.job.result["revisions"]) == 1
    assert session.commits == 1


@pytest.mark.asyncio
async def test_pack_handler_persists_full_schema_max_violation_then_requires_review(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture()
    fixture.raw["caption"] = "x" * 2_201
    run_id, attempt_id = uuid4(), uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[fixture.story, None, fixture.story, durable_run, None, None, None, None],
    )

    async def invoke(context, **kwargs):
        await kwargs["before_provider_call"]()
        authored = kwargs["validate_output"](fixture.raw)
        return SimpleNamespace(id=run_id), SimpleNamespace(id=attempt_id), authored

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision_value: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    revisions = [item for item in session.added if isinstance(item, PlatformVariantRevision)]
    assert caught.value.code == "platform_validation_failed"
    assert len(revisions) == 1
    assert len(revisions[0].content["caption"]) == 2_201
    assert revisions[0].approval_state == "pending_review"
    assert revisions[0].validation_results == [
        {
            "gate": "instagram_caption_too_long",
            "ok": False,
            "reason": "Caption is 2201/2200 characters",
        }
    ]
    assert fixture.job.result["revision_id"] == str(revisions[0].id)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_regeneration_rechecks_base_before_provider_and_creates_no_child(monkeypatch):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import PlatformVariantRevision
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture()
    pack_id, variant_id = uuid4(), uuid4()
    requested_base_id = uuid4()
    newer_parent = SimpleNamespace(
        id=uuid4(),
        platform_variant_id=variant_id,
        revision_number=2,
        content_hash="c" * 64,
    )
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="instagram")
    fixture.job.payload |= {
        "variant_id": str(variant_id),
        "base_revision_id": str(requested_base_id),
        "base_content_hash": "b" * 64,
    }
    run_id, attempt_id = uuid4(), uuid4()
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[
            fixture.story,
            None,
            variant,
            newer_parent,
        ],
    )
    provider_calls = 0

    async def invoke(context, **kwargs):
        nonlocal provider_calls
        await kwargs["before_provider_call"]()
        provider_calls += 1
        return (
            SimpleNamespace(id=run_id),
            SimpleNamespace(id=attempt_id),
            kwargs["validate_output"](fixture.raw),
        )

    async def recheck(session_value, platform, prompt_id, prompt_checksum):
        return fixture.prompts[platform]

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_active_prompt", recheck)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    with pytest.raises(NeedsReviewJobError) as caught:
        await build_pack_generation_handler(SimpleNamespace())(
            fixture.job,
            JobContext(session=session, providers=SimpleNamespace()),
        )

    assert caught.value.code == "generation_regeneration_base_stale"
    assert provider_calls == 0
    assert not any(isinstance(item, PlatformVariantRevision) for item in session.added)


@pytest.mark.parametrize("cached_success", [False, True])
@pytest.mark.asyncio
async def test_regeneration_fence_survives_provider_and_cached_success_until_child_commit(
    monkeypatch,
    cached_success,
):
    from app.generation.handlers import build_pack_generation_handler
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.generation.revision_fence import (
        REGENERATION_FENCE_RESULT_KEY,
        RegenerationFenceOwner,
    )
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture()
    pack_id, variant_id, base_id = uuid4(), uuid4(), uuid4()
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=fixture.story_revision.id,
        brand_profile_id=fixture.brand.id,
    )
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="instagram")
    base = SimpleNamespace(
        id=base_id,
        platform_variant_id=variant_id,
        revision_number=1,
        content_hash="b" * 64,
    )
    fixture.job.payload |= {
        "variant_id": str(variant_id),
        "base_revision_id": str(base_id),
        "base_content_hash": base.content_hash,
    }
    fixture.job.status = "running"
    fixture.job.lease_owner = "worker-fence"
    fixture.job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    owner = RegenerationFenceOwner(
        workflow_job_id=fixture.job.id,
        workflow_attempt=fixture.job.attempt_count,
        lease_owner=fixture.job.lease_owner,
    )
    run_id, attempt_id = uuid4(), uuid4()
    durable_run = SimpleNamespace(id=run_id, output_payload={})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[
            fixture.story,
            pack.id,
            fixture.story,
            durable_run,
            pack,
            variant,
            None,
            base,
        ],
        objects={(ContentPack, pack_id): pack, (PlatformVariant, variant_id): variant},
    )
    events = []

    async def dispatch(session_value, **kwargs):
        assert kwargs["workflow_job_id"] == fixture.job.id
        assert kwargs["workflow_attempt"] == fixture.job.attempt_count
        assert kwargs["lease_owner"] == fixture.job.lease_owner
        events.append("acquire")
        fixture.job.result[REGENERATION_FENCE_RESULT_KEY] = {
            "variant_id": str(variant_id),
            "base_revision_id": str(base_id),
            "base_content_hash": base.content_hash,
            "workflow_job_id": str(fixture.job.id),
            "workflow_attempt": fixture.job.attempt_count,
            "lease_owner": fixture.job.lease_owner,
        }
        return owner

    async def require_owner(session_value, **kwargs):
        assert kwargs == {
            "variant_id": variant_id,
            "owner": owner,
            "expected_base_revision_id": base_id,
            "expected_base_content_hash": base.content_hash,
        }
        events.append("recheck")

    async def invoke(context, **kwargs):
        if not cached_success:
            await kwargs["before_provider_call"]()
            await context.session.commit()
            events.append("provider")
        authored = kwargs["validate_output"](fixture.raw)
        return durable_run, SimpleNamespace(id=attempt_id), authored

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._require_exact_regeneration_dispatch", dispatch)
    monkeypatch.setattr("app.generation.handlers.require_revision_write_allowed", require_owner)
    monkeypatch.setattr("app.generation.handlers._invoke", invoke)

    result = await build_pack_generation_handler(SimpleNamespace())(
        fixture.job,
        JobContext(session=session, providers=SimpleNamespace()),
    )

    assert events == (["acquire", "recheck"] if cached_success else ["acquire", "provider", "recheck"])
    assert REGENERATION_FENCE_RESULT_KEY not in fixture.job.result
    child = next(item for item in session.added if isinstance(item, PlatformVariantRevision))
    assert child.parent_revision_id == base_id
    assert result["revision_id"] == str(child.id)


@pytest.mark.asyncio
async def test_platform_stage_retry_reuses_durable_attempt_without_second_provider_call():
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile, GenerationAttempt, GenerationRun
    from app.jobs.registry import JobContext
    from tests.generation.test_editorial_service import _lifecycle_prompt, _LifecycleSession

    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    prompt = _lifecycle_prompt()
    job_id = uuid4()
    stage_hash = "a" * 64
    durable_hash = sha256_canonical(
        {
            "workflow_job_id": str(job_id),
            "stage_input_hash": stage_hash,
            "resolved_model": "fake-v1",
            "purpose": "instagram_pack",
        }
    )
    run = GenerationRun(
        id=uuid4(),
        story_revision_id=None,
        provider_profile_id=profile.id,
        prompt_template_version_id=prompt.id,
        requested_model="fake-v1",
        status="succeeded",
        input_hash=durable_hash,
        request_payload={},
        output_payload={"ok": True},
    )
    attempt = GenerationAttempt(
        id=uuid4(),
        generation_run_id=run.id,
        attempt_number=1,
        provider="fake",
        requested_model="fake-v1",
        resolved_model="fake-v1",
        prompt_snapshot={},
        response_payload={"ok": True},
        usage={},
        validation_errors=[],
        status="succeeded",
        started_at=datetime.now(UTC),
    )
    session = _LifecycleSession(existing=run, completed_attempt=attempt)
    session.profile = profile
    calls = 0

    class Provider:
        async def generate(self, request):
            nonlocal calls
            calls += 1
            raise AssertionError("durable retry called the provider twice")

    async def resolve(profile_value, model_override):
        return SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1")

    reused = await _invoke(
        JobContext(session=session, providers=SimpleNamespace()),
        profile_resolver=SimpleNamespace(resolve=resolve),
        profile_id=profile.id,
        prompt=prompt,
        purpose="instagram_pack",
        story_revision_id=None,
        input_payload={"value": "executed"},
        input_hash=stage_hash,
        workflow_job_id=job_id,
        workflow_attempt=2,
        validate_output=lambda value: value,
    )

    assert (reused[0].id, reused[1].id, reused[2]) == (run.id, attempt.id, {"ok": True})
    assert calls == 0


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("citation", "citation_integrity"),
        ("schema", "generation_output_invalid"),
        ("value", "generation_output_invalid"),
    ],
)
@pytest.mark.asyncio
async def test_durable_success_revalidation_failure_is_sanitized_needs_review_without_attempt_mutation(
    failure,
    expected_code,
):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.handlers import _invoke
    from app.generation.models import AIProviderProfile, GenerationAttempt, GenerationRun
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext
    from tests.generation.test_editorial_service import _lifecycle_prompt, _LifecycleSession

    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    prompt = _lifecycle_prompt()
    job_id = uuid4()
    stage_hash = "a" * 64
    durable_hash = sha256_canonical(
        {
            "workflow_job_id": str(job_id),
            "stage_input_hash": stage_hash,
            "resolved_model": "fake-v1",
            "purpose": "instagram_pack",
        }
    )
    run = GenerationRun(
        id=uuid4(),
        story_revision_id=None,
        provider_profile_id=profile.id,
        prompt_template_version_id=prompt.id,
        requested_model="fake-v1",
        status="succeeded",
        input_hash=durable_hash,
        request_payload={},
        output_payload={"ok": True},
    )
    attempt = GenerationAttempt(
        id=uuid4(),
        generation_run_id=run.id,
        attempt_number=1,
        provider="fake",
        requested_model="fake-v1",
        resolved_model="fake-v1",
        prompt_snapshot={},
        response_payload={"ok": True},
        usage={},
        validation_errors=[],
        status="succeeded",
        started_at=datetime.now(UTC),
    )
    session = _LifecycleSession(existing=run, completed_attempt=attempt)
    session.profile = profile
    provider_calls = 0

    class Provider:
        async def generate(self, request):
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("durable success must not call the provider")

    async def resolve(profile_value, model_override):
        return SimpleNamespace(provider=Provider(), provider_type="fake", model="fake-v1")

    def validate_output(value):
        if failure == "citation":
            raise CitationIntegrityError("unsafe citation detail")
        if failure == "schema":
            TelegramVariantPayload.model_validate(value)
        raise ValueError("unsafe validation detail")

    with pytest.raises(NeedsReviewJobError) as caught:
        await _invoke(
            JobContext(session=session, providers=SimpleNamespace()),
            profile_resolver=SimpleNamespace(resolve=resolve),
            profile_id=profile.id,
            prompt=prompt,
            purpose="instagram_pack",
            story_revision_id=None,
            input_payload={"value": "executed"},
            input_hash=stage_hash,
            workflow_job_id=job_id,
            workflow_attempt=2,
            validate_output=validate_output,
        )

    assert caught.value.code == expected_code
    assert "unsafe" not in caught.value.message
    assert run.status == "succeeded"
    assert attempt.status == "succeeded"
    assert attempt.validation_errors == []
    assert provider_calls == 0


@pytest.mark.asyncio
async def test_regeneration_idempotency_is_bound_to_locked_current_revision():
    from app.generation.editorial_service import EditorialService, RegenerateVariantRequest

    profile = SimpleNamespace(
        id=uuid4(),
        enabled=True,
        default_model="fake-v1",
        provider_type="fake",
        secret_ref=None,
        settings={},
    )
    variant = SimpleNamespace(id=uuid4(), platform="instagram")
    prompt = SimpleNamespace(id=uuid4(), checksum_sha256="a" * 64)
    first_revision = SimpleNamespace(id=uuid4(), content_hash="b" * 64)
    second_revision = SimpleNamespace(id=uuid4(), content_hash="c" * 64)

    class Session:
        def __init__(self):
            self.current = first_revision
            self.scalar_calls = 0

        async def scalar(self, statement):
            selected = (profile, variant, self.current)[self.scalar_calls % 3]
            self.scalar_calls += 1
            return selected

        async def scalars(self, statement):
            assert statement._for_update_arg is None
            return [prompt]

    class Jobs:
        def __init__(self):
            self.by_key = {}
            self.calls = []

        async def enqueue_job(self, **kwargs):
            self.calls.append(kwargs)
            key = kwargs["idempotency_key"]
            created = key not in self.by_key
            if created:
                self.by_key[key] = SimpleNamespace(id=uuid4(), status="queued")
            return SimpleNamespace(job=self.by_key[key], created=created)

    session = Session()
    jobs = Jobs()
    service = EditorialService(session, jobs=jobs)
    request = RegenerateVariantRequest(
        generation_provider_profile_id=profile.id,
        instruction="Try a sharper hook",
    )

    first = await service.regenerate_variant(variant.id, request)
    retry = await service.regenerate_variant(variant.id, request)
    session.current = second_revision
    after_new_current = await service.regenerate_variant(variant.id, request)

    assert first.deduplicated is False
    assert retry.deduplicated is True
    assert retry.job_id == first.job_id
    assert after_new_current.deduplicated is False
    assert after_new_current.job_id != first.job_id
    assert jobs.calls[0]["payload"]["base_revision_id"] == str(first_revision.id)
    assert jobs.calls[0]["payload"]["base_content_hash"] == first_revision.content_hash
    assert jobs.calls[2]["payload"]["base_revision_id"] == str(second_revision.id)
    assert jobs.calls[2]["payload"]["base_content_hash"] == second_revision.content_hash


@pytest.mark.asyncio
async def test_regeneration_wrapper_holds_no_row_locks_across_pack_delegation(monkeypatch):
    from app.generation.handlers import build_regenerate_handler
    from app.generation.models import ContentPack, PlatformVariant
    from app.jobs.registry import JobContext

    variant = SimpleNamespace(id=uuid4(), content_pack_id=uuid4(), platform="instagram")
    pack = SimpleNamespace(
        id=variant.content_pack_id,
        story_revision_id=uuid4(),
        brand_profile_id=uuid4(),
    )
    current = SimpleNamespace(id=uuid4(), content_hash="b" * 64)
    events = []

    class Session:
        async def get(self, model, identifier):
            assert model is ContentPack and identifier == pack.id
            events.append("get_pack")
            return pack

        async def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            assert statement._for_update_arg is None
            events.append(f"read_{entity.__name__}")
            assert entity is PlatformVariant
            return variant

    def pack_builder(profile_resolver):
        async def handle(job, context):
            events.append("delegate")
            return {"locked": True}

        return handle

    monkeypatch.setattr("app.generation.handlers.build_pack_generation_handler", pack_builder)
    job = SimpleNamespace(
        payload={
            "variant_id": str(variant.id),
            "base_revision_id": str(current.id),
            "base_content_hash": current.content_hash,
            "platforms": ["instagram"],
            "platform_prompt_template_version_ids": {"instagram": str(uuid4())},
            "platform_prompt_checksums": {"instagram": "c" * 64},
        }
    )

    result = await build_regenerate_handler(SimpleNamespace())(
        job,
        JobContext(session=Session(), providers=SimpleNamespace()),
    )

    assert result == {"locked": True}
    assert events == [
        "read_PlatformVariant",
        "get_pack",
        "delegate",
    ]


@pytest.mark.asyncio
async def test_regeneration_retry_delegates_after_committed_child_becomes_current(monkeypatch):
    from app.generation.handlers import build_regenerate_handler
    from app.generation.models import ContentPack, PlatformVariant
    from app.jobs.registry import JobContext

    variant_id = uuid4()
    pack_id = uuid4()
    requested_base_id = uuid4()
    current = SimpleNamespace(id=uuid4(), content_hash="c" * 64)
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="instagram")
    pack = SimpleNamespace(id=pack_id, story_revision_id=uuid4(), brand_profile_id=uuid4())

    class Session:
        async def get(self, model, identifier):
            if model is PlatformVariant and identifier == variant_id:
                return variant
            if model is ContentPack and identifier == pack_id:
                return pack
            return None

        async def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            return variant if entity is PlatformVariant else current

    delegated = 0

    def pack_builder(profile_resolver):
        async def handle(job, context):
            nonlocal delegated
            delegated += 1
            return {"replayed": True}

        return handle

    monkeypatch.setattr("app.generation.handlers.build_pack_generation_handler", pack_builder)
    job = SimpleNamespace(
        payload={
            "variant_id": str(variant_id),
            "base_revision_id": str(requested_base_id),
            "base_content_hash": "b" * 64,
            "platforms": ["instagram"],
            "platform_prompt_template_version_ids": {"instagram": str(uuid4())},
            "platform_prompt_checksums": {"instagram": "d" * 64},
        }
    )

    result = await build_regenerate_handler(SimpleNamespace())(
        job,
        JobContext(session=Session(), providers=SimpleNamespace()),
    )

    assert result == {"replayed": True}
    assert delegated == 1
    assert job.payload["story_revision_id"] == str(pack.story_revision_id)
    assert job.payload["brand_profile_id"] == str(pack.brand_profile_id)


@pytest.mark.asyncio
async def test_regeneration_terminal_failure_clears_exact_owned_fence(monkeypatch):
    from app.generation.handlers import build_regenerate_handler
    from app.generation.models import ContentPack, PlatformVariant
    from app.generation.revision_fence import RegenerationFenceOwner
    from app.jobs.errors import NeedsReviewJobError
    from app.jobs.registry import JobContext

    variant = SimpleNamespace(id=uuid4(), content_pack_id=uuid4(), platform="instagram")
    pack = SimpleNamespace(
        id=variant.content_pack_id,
        story_revision_id=uuid4(),
        brand_profile_id=uuid4(),
    )
    current = SimpleNamespace(id=uuid4(), content_hash="b" * 64)
    events = []

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        async def get(self, model, identifier):
            if model is PlatformVariant:
                return variant
            if model is ContentPack:
                return pack
            return None

        async def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            return variant if entity is PlatformVariant else current

        async def rollback(self):
            events.append("rollback")

        async def commit(self):
            events.append("commit")

    async def clear(session, **kwargs):
        assert kwargs == {
            "variant_id": variant.id,
            "owner": RegenerationFenceOwner(
                workflow_job_id=job.id,
                workflow_attempt=job.attempt_count,
                lease_owner=job.lease_owner,
            ),
        }
        events.append("clear")
        return True

    def pack_builder(profile_resolver):
        async def handle(job_value, context):
            events.append("delegate")
            raise NeedsReviewJobError(code="platform_validation_failed", message="Needs review")

        return handle

    monkeypatch.setattr("app.generation.handlers.build_pack_generation_handler", pack_builder)
    monkeypatch.setattr("app.generation.handlers.clear_regeneration_fence", clear)
    job = SimpleNamespace(
        id=uuid4(),
        attempt_count=2,
        lease_owner="worker-fence",
        payload={
            "variant_id": str(variant.id),
            "base_revision_id": str(current.id),
            "base_content_hash": current.content_hash,
            "platforms": ["instagram"],
            "platform_prompt_template_version_ids": {"instagram": str(uuid4())},
            "platform_prompt_checksums": {"instagram": "d" * 64},
        },
    )

    with pytest.raises(NeedsReviewJobError):
        await build_regenerate_handler(SimpleNamespace())(
            job,
            JobContext(session=Session(), providers=SimpleNamespace()),
        )

    assert events == ["delegate", "rollback", "clear", "commit"]


@pytest.mark.asyncio
async def test_regeneration_retry_replays_actual_committed_artifact_bound_to_immutable_base(monkeypatch):
    from app.automations.telegram.handlers import sha256_canonical
    from app.generation.handlers import build_regenerate_handler
    from app.generation.models import ContentPack, PlatformVariant
    from app.jobs.registry import JobContext

    fixture = _pack_handler_fixture()
    pack_id, variant_id, base_id, revision_id, run_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    authored, issues = _manual_output_with_ordinary_issues("instagram", fixture.raw)
    content = authored.model_dump(mode="json")
    evidence_map = [item.model_dump(mode="json") for item in ordered_distinct_citations(authored)]
    gates = revision_gates_from_issues(issues)
    pack = SimpleNamespace(
        id=pack_id,
        story_revision_id=fixture.story_revision.id,
        brand_profile_id=fixture.brand.id,
    )
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="instagram")
    base = SimpleNamespace(
        id=base_id,
        platform_variant_id=variant_id,
        content_hash="b" * 64,
        revision_number=1,
    )
    child = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        parent_revision_id=base_id,
        generation_attempt_id=attempt_id,
        revision_number=2,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=gates,
    )
    artifact = {
        "content_pack_id": str(pack_id),
        "variant_id": str(variant_id),
        "revision_id": str(revision_id),
        "platform": "instagram",
    }
    durable_run = SimpleNamespace(id=run_id, output_payload={"_artifact": artifact})
    session = _PackHandlerSession(
        story_revision=fixture.story_revision,
        brand=fixture.brand,
        prompts=[fixture.prompts["instagram"]],
        scalar_values=[
            variant,
            fixture.story,
            pack.id,
            fixture.story,
            durable_run,
            pack,
            variant,
            child,
            base,
        ],
        objects={(ContentPack, pack_id): pack, (PlatformVariant, variant_id): variant},
    )
    fixture.job.payload |= {
        "variant_id": str(variant_id),
        "base_revision_id": str(base_id),
        "base_content_hash": base.content_hash,
    }

    async def cached_invoke(context, **kwargs):
        assert "before_provider_call" in kwargs
        return durable_run, SimpleNamespace(id=attempt_id), authored

    monkeypatch.setattr(
        "app.generation.handlers._locked_story_evidence",
        lambda context, revision: _resolved(([fixture.ref], fixture.evidence)),
    )
    monkeypatch.setattr(
        "app.generation.handlers._trusted_story_media",
        lambda session_value, evidence, **kwargs: _resolved(({}, [])),
    )
    monkeypatch.setattr("app.generation.handlers._invoke", cached_invoke)

    result = await build_regenerate_handler(SimpleNamespace())(
        fixture.job,
        JobContext(session=session, providers=SimpleNamespace()),
    )

    assert result["revision_id"] == str(revision_id)
    assert result["variant_id"] == str(variant_id)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_regeneration_handler_rejects_target_platform_mismatch(monkeypatch):
    from app.generation.handlers import build_regenerate_handler
    from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
    from app.jobs.errors import PermanentJobError
    from app.jobs.registry import JobContext

    target_platform = "instagram"
    variant = SimpleNamespace(id=uuid4(), content_pack_id=uuid4(), platform=target_platform)
    pack = SimpleNamespace(
        id=variant.content_pack_id,
        story_revision_id=uuid4(),
        brand_profile_id=uuid4(),
    )
    current = SimpleNamespace(id=uuid4(), content_hash="b" * 64)

    class Session:
        async def get(self, model, identifier):
            if model is PlatformVariant:
                return variant
            if model is ContentPack:
                return pack
            return None

        async def scalar(self, statement):
            if statement.column_descriptions[0]["entity"] is PlatformVariantRevision:
                return current
            return None

    delegated = 0

    def pack_builder(profile_resolver):
        async def handle(job, context):
            nonlocal delegated
            delegated += 1
            return {}

        return handle

    monkeypatch.setattr("app.generation.handlers.build_pack_generation_handler", pack_builder)
    payload = {
        "variant_id": str(variant.id),
        "generation_provider_profile_id": str(uuid4()),
    }
    payload |= {
        "base_revision_id": str(current.id),
        "base_content_hash": current.content_hash,
        "platforms": ["blog"],
        "platform_prompt_template_version_ids": {"blog": str(uuid4())},
        "platform_prompt_checksums": {"blog": "c" * 64},
    }

    with pytest.raises(PermanentJobError):
        await build_regenerate_handler(SimpleNamespace())(
            SimpleNamespace(payload=payload),
            JobContext(session=Session(), providers=SimpleNamespace()),
        )

    assert delegated == 0
