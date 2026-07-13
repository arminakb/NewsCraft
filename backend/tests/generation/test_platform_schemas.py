from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    TelegramVariantPayload,
    XVariantPayload,
)
from app.generation.telegram_schema import TelegramVariantContent
from app.publishing.telegram.renderer import build_publish_plan


def citation_ref(*, source_url: str | None = "https://example.com/report") -> dict[str, object]:
    return {
        "evidence_key": f"evidence:{uuid4()}",
        "evidence_snapshot_id": uuid4(),
        "source_url": source_url,
        "locator": "chars:0-12",
        "excerpt_sha256": "a" * 64,
    }


def media_assignment(*, order: int = 1, role: str = "slide") -> dict[str, object]:
    return {
        "media_asset_id": uuid4(),
        "role": role,
        "order": order,
        "alt_text": "A descriptive alternative for the assigned image",
        "manual_brief": "Use the source image without decorative text",
        "image_prompt": None,
    }


def instagram_payload() -> dict[str, object]:
    return {
        "hook": "What changed?",
        "caption": "A grounded caption for a manual Instagram post.",
        "cta": "Read the cited report.",
        "hashtags": ["#AI", "#NewsCraft"],
        "alt_text": "Two slides summarize the cited report.",
        "carousel": [
            {
                "order": 1,
                "headline": "The update",
                "body": "What the source confirms.",
                "media": media_assignment(order=1),
            },
            {
                "order": 2,
                "headline": "Why it matters",
                "body": "The supported consequence.",
                "media": media_assignment(order=2),
            },
        ],
        "citations": [citation_ref()],
        "manual_checklist": ["Verify carousel order before publishing"],
    }


def test_instagram_package_contains_publishable_copy_carousel_alt_text_and_checklist():
    value = InstagramVariantPayload.model_validate(instagram_payload())

    assert value.caption
    assert value.hook
    assert value.cta
    assert value.hashtags == ["#AI", "#NewsCraft"]
    assert value.alt_text
    assert [slide.order for slide in value.carousel] == [1, 2]
    assert value.manual_checklist


def test_schema_limits_reject_unpublishable_or_inaccessible_payloads():
    invalid_instagram = instagram_payload()
    invalid_instagram["caption"] = "x" * 2_201
    with pytest.raises(ValidationError):
        InstagramVariantPayload.model_validate(invalid_instagram)

    invalid_media = media_assignment()
    invalid_media["alt_text"] = ""
    invalid_x = {
        "mode": "single",
        "posts": [
            {
                "order": 1,
                "text": "A supported post",
                "media": [invalid_media],
                "citations": [citation_ref()],
            }
        ],
        "link_strategy": "last_post",
        "manual_checklist": ["Verify copy"],
    }
    with pytest.raises(ValidationError):
        XVariantPayload.model_validate(invalid_x)


@pytest.mark.parametrize("platform", ["instagram", "x", "blog"])
def test_manual_platform_citations_reject_url_userinfo(platform):
    unsafe_citation = citation_ref(source_url="https://user:password@example.com/report")
    if platform == "instagram":
        payload = {**instagram_payload(), "citations": [unsafe_citation]}
        model = InstagramVariantPayload
    elif platform == "x":
        payload = {
            "mode": "single",
            "posts": [
                {
                    "order": 1,
                    "text": "A supported post",
                    "media": [],
                    "citations": [unsafe_citation],
                }
            ],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify copy"],
        }
        model = XVariantPayload
    else:
        payload = {
            "title": "A complete grounded blog package",
            "slug": "complete-grounded-blog-package",
            "excerpt": "A concise summary of the grounded article.",
            "body_markdown": "## What happened\n\n" + "Grounded article content. " * 12,
            "headings": ["What happened"],
            "citations": [unsafe_citation],
            "tags": ["news"],
            "seo_description": "A complete search description grounded in the available source material.",
            "hero_media": None,
            "canonical_sources": [],
            "manual_checklist": ["Check links before publishing"],
        }
        model = BlogVariantPayload

    with pytest.raises(ValidationError, match="userinfo"):
        model.model_validate(payload)


def test_blog_canonical_sources_reject_url_userinfo_before_serialization():
    payload = {
        "title": "A complete grounded blog package",
        "slug": "complete-grounded-blog-package",
        "excerpt": "A concise summary of the grounded article.",
        "body_markdown": "## What happened\n\n" + "Grounded article content. " * 12,
        "headings": ["What happened"],
        "citations": [citation_ref()],
        "tags": ["news"],
        "seo_description": "A complete search description grounded in the available source material.",
        "hero_media": None,
        "canonical_sources": ["https://user:password@example.com/report"],
        "manual_checklist": ["Check links before publishing"],
    }

    with pytest.raises(ValidationError, match="userinfo"):
        BlogVariantPayload.model_validate(payload)


def test_blog_shape_requires_complete_seo_but_allows_citations_to_be_validated_later():
    value = BlogVariantPayload.model_validate(
        {
            "title": "A complete grounded blog package",
            "slug": "complete-grounded-blog-package",
            "excerpt": "A concise summary of the grounded article.",
            "body_markdown": "## What happened\n\n" + "Grounded article content. " * 12,
            "headings": ["What happened"],
            "citations": [],
            "tags": ["news"],
            "seo_description": "A complete search description grounded in the available source material.",
            "hero_media": None,
            "canonical_sources": [],
            "manual_checklist": ["Check links before publishing"],
        }
    )

    assert value.citations == []
    with pytest.raises(ValidationError):
        BlogVariantPayload.model_validate({**value.model_dump(), "seo_description": "too short"})


def test_telegram_payload_is_the_exact_release_two_content_contract():
    stored = {
        "body": '<strong dir="rtl">خبر</strong>',
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }

    # TelegramVariantPayload must inherit, not fork, the Release 2 validator.
    assert issubclass(TelegramVariantPayload, TelegramVariantContent)
    assert TelegramVariantPayload.__name__ == "TelegramVariantPayload"
    with pytest.raises(ValidationError):
        TelegramVariantPayload.model_validate(stored)

    stored["body"] = "<strong>خبر</strong>"
    payload = TelegramVariantPayload.model_validate(stored)
    assert payload.model_dump(mode="json") == stored

    with pytest.raises(ValidationError):
        TelegramVariantPayload.model_validate({**stored, "citations": [citation_ref()]})


def test_telegram_json_bytes_match_release_two_with_uuid_and_normalized_source_url():
    stored = {
        "body": "<strong>Grounded update</strong>",
        "parse_mode": "HTML",
        "buttons": [{"text": "Source", "url": "https://EXAMPLE.com:443/report"}],
        "source_item_id": uuid4(),
        "source_url": "https://EXAMPLE.com:443/report",
        "media_policy": "preserve",
        "media_asset_ids": [uuid4()],
        "direction": "rtl",
        "dry_run": True,
    }

    compatibility = TelegramVariantPayload.model_validate(stored)
    release_two = TelegramVariantContent.model_validate(stored)

    assert compatibility.model_dump(mode="json") == release_two.model_dump(mode="json")
    assert compatibility.model_dump_json() == release_two.model_dump_json()


def test_telegram_json_bytes_match_release_two_with_nullable_identity_and_source():
    stored = {
        "body": "Operator-authored update",
        "parse_mode": "HTML",
        "buttons": [],
        "source_item_id": None,
        "source_url": None,
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "ltr",
        "dry_run": False,
    }

    assert TelegramVariantPayload.model_validate(stored).model_dump_json() == (
        TelegramVariantContent.model_validate(stored).model_dump_json()
    )


def test_telegram_payload_preserves_release_two_renderer_plan():
    stored = {
        "body": "<strong>Operator-authored update</strong>",
        "parse_mode": "HTML",
        "buttons": [{"text": "Source", "url": "https://example.com/report"}],
        "source_item_id": None,
        "source_url": "https://example.com/report",
        "media_policy": "omit",
        "media_asset_ids": [],
        "direction": "rtl",
        "dry_run": False,
    }
    revision_id = uuid4()
    destination = SimpleNamespace(id=uuid4(), target_ref="@newscraft_test")
    compatibility_revision = SimpleNamespace(
        id=revision_id,
        content=TelegramVariantPayload.model_validate(stored).model_dump(mode="json"),
    )
    release_two_revision = SimpleNamespace(
        id=revision_id,
        content=TelegramVariantContent.model_validate(stored).model_dump(mode="json"),
    )

    assert build_publish_plan(compatibility_revision, [], destination) == build_publish_plan(
        release_two_revision, [], destination
    )
