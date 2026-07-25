from uuid import uuid4

import pytest

from app.generation.platform_limits import x_weighted_length
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    XPost,
    XVariantPayload,
)
from app.generation.platform_validation import ValidationIssue, validate_platform_payload


def citation_ref(*, source_url: str | None = "https://example.com/report") -> dict[str, object]:
    return {
        "evidence_key": f"evidence:{uuid4()}",
        "evidence_snapshot_id": uuid4(),
        "source_url": source_url,
        "locator": "chars:0-12",
        "excerpt_sha256": "b" * 64,
    }


def media_assignment(*, media_asset_id=None, order: int = 1, role: str = "post") -> dict[str, object]:
    return {
        "media_asset_id": media_asset_id if media_asset_id is not None else uuid4(),
        "role": role,
        "order": order,
        "alt_text": "A meaningful description of the source image",
        "manual_brief": None,
        "image_prompt": None,
    }


def blog_payload(*, citations, canonical_sources) -> dict[str, object]:
    return {
        "title": "A complete grounded blog package",
        "slug": "complete-grounded-blog-package",
        "excerpt": "A concise summary of the grounded article.",
        "body_markdown": "## What happened\n\n" + "Grounded article content. " * 12,
        "headings": ["What happened"],
        "citations": citations,
        "tags": ["news"],
        "seo_description": "A complete search description grounded in the available source material.",
        "hero_media": None,
        "canonical_sources": canonical_sources,
        "manual_checklist": ["Check links before publishing"],
    }


def test_x_validator_reports_exact_segment_and_weighted_length():
    value = XVariantPayload(
        mode="thread",
        posts=[XPost(order=1, text="a" * 281, media=[], citations=[citation_ref()])],
        link_strategy="last_post",
        manual_checklist=["Verify thread order before posting"],
    )

    issues = validate_platform_payload("x", value)

    assert [issue for issue in issues if issue.severity == "error"] == [
        ValidationIssue(
            code="x_post_too_long",
            path="posts.0.text",
            message="Post 1 is 281/280 weighted characters",
        )
    ]
    assert any(issue.code == "x_platform_recheck_required" and issue.severity == "warning" for issue in issues)


def test_x_weighted_length_counts_urls_as_23_and_every_other_code_point_once():
    assert x_weighted_length("الف https://example.com/a/very/long/path پایان") == 3 + 1 + 23 + 1 + 5
    assert x_weighted_length("🙂") == 1


def test_x_weighted_length_excludes_surrounding_punctuation_and_handles_multiple_urls():
    # Outside the URLs: emoji, spaces, comma, "and", and period total nine code points.
    assert x_weighted_length("🙂 https://a.example/x, and https://b.example/y.") == 23 + 23 + 9


def test_x_weighted_length_keeps_balanced_url_parentheses_and_ignores_sentence_punctuation():
    assert x_weighted_length("https://example.com/report_(final).") == 23 + 1
    assert x_weighted_length("http://[::1]/report") == 23


@pytest.mark.parametrize("malformed", ["https://?", "http://)"])
def test_x_weighted_length_counts_malformed_url_candidates_as_ordinary_code_points(malformed):
    assert x_weighted_length(malformed) == len(malformed)


def test_x_exact_280_with_valid_parenthesized_url_has_no_length_error():
    value = XVariantPayload(
        mode="single",
        posts=[
            XPost(
                order=1,
                text=("a" * 256) + " " + "https://example.com/report_(final)",
                media=[],
                citations=[citation_ref()],
            )
        ],
        link_strategy="last_post",
        manual_checklist=["Verify post before publishing"],
    )

    assert "x_post_too_long" not in {issue.code for issue in validate_platform_payload("x", value)}


def test_x_validator_enforces_order_mode_and_unique_media_assignments():
    shared_id = uuid4()
    value = XVariantPayload(
        mode="single",
        posts=[
            XPost(
                order=2,
                text="First factual post",
                media=[media_assignment(media_asset_id=shared_id)],
                citations=[citation_ref()],
            ),
            XPost(
                order=3,
                text="Second factual post",
                media=[media_assignment(media_asset_id=shared_id)],
                citations=[citation_ref()],
            ),
        ],
        link_strategy="each_post",
        manual_checklist=["Verify post order"],
    )

    codes = {issue.code for issue in validate_platform_payload("x", value)}

    assert {"x_single_requires_one_post", "x_post_order_invalid", "x_duplicate_media_assignment"} <= codes


@pytest.mark.parametrize("orders", [[1, 1], [1, 3]])
def test_x_validator_rejects_duplicate_or_gapped_post_order(orders):
    value = XVariantPayload(
        mode="thread",
        posts=[
            XPost(order=order, text=f"Post {index}", media=[], citations=[citation_ref()])
            for index, order in enumerate(orders, start=1)
        ],
        link_strategy="last_post",
        manual_checklist=["Verify thread order"],
    )

    assert "x_post_order_invalid" in {issue.code for issue in validate_platform_payload("x", value)}


@pytest.mark.parametrize("orders", [[1, 1], [1, 3]])
def test_instagram_validator_rejects_duplicate_or_gapped_carousel_order(orders):
    value = InstagramVariantPayload.model_validate(
        {
            "hook": "Hook",
            "caption": "Caption",
            "cta": "Read more",
            "hashtags": ["#News"],
            "alt_text": "Summary of the two slides",
            "carousel": [
                {
                    "order": order,
                    "headline": f"Slide {index}",
                    "body": "Grounded body",
                    "media": media_assignment(order=order, role="slide"),
                }
                for index, order in enumerate(orders, start=1)
            ],
            "citations": [citation_ref()],
            "manual_checklist": ["Verify slide order"],
        }
    )

    assert "instagram_carousel_order_invalid" in {issue.code for issue in validate_platform_payload("instagram", value)}


def test_instagram_validator_rejects_duplicate_media_and_empty_hashtag_or_checklist_item():
    shared_id = uuid4()
    value = InstagramVariantPayload.model_validate(
        {
            "hook": "Hook",
            "caption": "Caption",
            "cta": "Read more",
            "hashtags": ["#News", ""],
            "alt_text": "Summary of the two slides",
            "carousel": [
                {
                    "order": order,
                    "headline": f"Slide {order}",
                    "body": "Grounded body",
                    "media": media_assignment(media_asset_id=shared_id, order=order, role="slide"),
                }
                for order in (1, 2)
            ],
            "citations": [citation_ref()],
            "manual_checklist": [""],
        }
    )

    codes = {issue.code for issue in validate_platform_payload("instagram", value)}
    assert {
        "instagram_duplicate_media_assignment",
        "instagram_empty_hashtag",
        "instagram_empty_checklist_item",
    } <= codes


def test_instagram_validator_rejects_blank_package_alt_text_and_misaligned_media_order():
    value = InstagramVariantPayload.model_validate(
        {
            "hook": "Hook",
            "caption": "Caption",
            "cta": "Read more",
            "hashtags": ["#News"],
            "alt_text": "   ",
            "carousel": [
                {
                    "order": 1,
                    "headline": "Slide 1",
                    "body": "Grounded body",
                    "media": media_assignment(order=2, role="slide"),
                }
            ],
            "citations": [citation_ref()],
            "manual_checklist": ["Verify slide order"],
        }
    )

    codes = {issue.code for issue in validate_platform_payload("instagram", value)}
    assert {"instagram_missing_alt_text", "instagram_media_order_invalid"} <= codes


def test_blog_requires_resolved_citations_and_complete_seo_fields():
    value = BlogVariantPayload.model_validate(blog_payload(citations=[], canonical_sources=[]))
    issues = validate_platform_payload("blog", value)
    assert {issue.code for issue in issues} == {"blog_missing_citations"}


def test_blog_canonical_sources_equal_distinct_non_null_citation_urls():
    citations = [
        citation_ref(source_url=None),
        citation_ref(source_url="https://example.com/report"),
        citation_ref(source_url="https://example.com/report"),
    ]
    valid = BlogVariantPayload.model_validate(
        blog_payload(citations=citations, canonical_sources=["https://example.com/report"])
    )
    assert "blog_canonical_sources_mismatch" not in {issue.code for issue in validate_platform_payload("blog", valid)}

    missing = BlogVariantPayload.model_validate(blog_payload(citations=citations, canonical_sources=[]))
    assert "blog_canonical_sources_mismatch" in {issue.code for issue in validate_platform_payload("blog", missing)}


def test_blog_canonical_sources_preserve_first_citation_order():
    citations = [
        citation_ref(source_url="https://example.com/second"),
        citation_ref(source_url="https://example.com/first"),
    ]
    reversed_sources = BlogVariantPayload.model_validate(
        blog_payload(
            citations=citations,
            canonical_sources=["https://example.com/first", "https://example.com/second"],
        )
    )
    assert "blog_canonical_sources_mismatch" in {
        issue.code for issue in validate_platform_payload("blog", reversed_sources)
    }


def test_blog_canonical_source_equality_uses_validated_url_normalization():
    value = BlogVariantPayload.model_validate(
        blog_payload(
            citations=[citation_ref(source_url="https://EXAMPLE.com:443/report")],
            canonical_sources=["https://example.com/report"],
        )
    )

    assert "blog_canonical_sources_mismatch" not in {issue.code for issue in validate_platform_payload("blog", value)}


def test_blog_with_only_manual_text_citations_keeps_canonical_sources_empty():
    value = BlogVariantPayload.model_validate(
        blog_payload(citations=[citation_ref(source_url=None)], canonical_sources=[])
    )
    assert "blog_canonical_sources_mismatch" not in {issue.code for issue in validate_platform_payload("blog", value)}


def test_blog_hero_media_order_must_be_one():
    value = BlogVariantPayload.model_validate(
        {
            **blog_payload(citations=[citation_ref()], canonical_sources=["https://example.com/report"]),
            "hero_media": media_assignment(order=2, role="hero"),
        }
    )

    assert validate_platform_payload("blog", value) == [
        ValidationIssue(
            code="blog_hero_media_order_invalid",
            path="hero_media.order",
            message="Hero media order must be 1",
        )
    ]


@pytest.mark.parametrize(
    ("media_policy", "media_asset_ids", "expected_codes"),
    [
        ("omit", [uuid4()], set()),
        ("preserve", [], set()),
        ("preserve", [uuid4()], set()),
        ("replace_manually", [], {"telegram_requires_manual_media_replacement"}),
    ],
)
def test_telegram_validation_delegates_release_two_renderability_policy(media_policy, media_asset_ids, expected_codes):
    from app.generation.platform_schemas import TelegramVariantPayload

    payload = TelegramVariantPayload.model_validate(
        {
            "body": "Grounded update",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": media_policy,
            "media_asset_ids": media_asset_ids,
            "direction": "rtl",
            "dry_run": False,
        }
    )

    issues = validate_platform_payload("telegram", payload)
    assert {issue.code for issue in issues} == expected_codes
    if media_policy == "replace_manually":
        assert issues == [
            ValidationIssue(
                code="telegram_requires_manual_media_replacement",
                path="media_policy",
                message="replace_manually revisions cannot be rendered",
            )
        ]


def test_validator_rejects_platform_and_payload_type_disagreement():
    instagram = InstagramVariantPayload.model_validate(
        {
            "hook": "Hook",
            "caption": "Caption",
            "cta": "Read more",
            "hashtags": [],
            "alt_text": "Text-only post",
            "carousel": [],
            "citations": [citation_ref()],
            "manual_checklist": ["Verify caption"],
        }
    )

    issues = validate_platform_payload("blog", instagram)

    assert issues == [
        ValidationIssue(
            code="platform_payload_type_mismatch",
            path="platform",
            message="Platform blog requires BlogVariantPayload",
        )
    ]


def test_validator_rejects_unknown_platform_at_runtime():
    with pytest.raises(ValueError, match="Unsupported platform"):
        validate_platform_payload("linkedin", object())  # type: ignore[arg-type]
