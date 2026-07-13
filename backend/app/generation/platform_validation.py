from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.generation.platform_limits import (
    BLOG_SEO_DESCRIPTION_MAX,
    INSTAGRAM_CAPTION_MAX,
    INSTAGRAM_CAROUSEL_MAX,
    INSTAGRAM_HASHTAG_MAX,
    X_MEDIA_PER_POST_MAX,
    X_POST_WEIGHT_MAX,
    x_weighted_length,
)
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    Platform,
    PlatformPayload,
    TelegramVariantPayload,
    XVariantPayload,
)
from app.publishing.telegram.renderer import TelegramPublishNeedsReview, validate_renderability_policy


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"


def _issue(code: str, path: str, message: str, *, severity: Literal["error", "warning"] = "error"):
    return ValidationIssue(code=code, path=path, message=message, severity=severity)


def _sequential(values: Iterable[int]) -> bool:
    ordered = list(values)
    return ordered == list(range(1, len(ordered) + 1))


def _duplicate_media_ids(assignments: Iterable[object]) -> bool:
    seen: set[UUID] = set()
    for assignment in assignments:
        media_asset_id = getattr(assignment, "media_asset_id", None)
        if media_asset_id is None:
            continue
        if media_asset_id in seen:
            return True
        seen.add(media_asset_id)
    return False


def _empty_checklist_issues(platform: str, checklist: list[str]) -> list[ValidationIssue]:
    return [
        _issue(
            f"{platform}_empty_checklist_item",
            f"manual_checklist.{index}",
            "Manual checklist items must not be empty",
        )
        for index, item in enumerate(checklist)
        if not item.strip()
    ]


def _validate_telegram(payload: TelegramVariantPayload) -> list[ValidationIssue]:
    # Re-validation deliberately delegates HTML, button, body, and stored media
    # shape checks to the Release 2 model. The publisher remains the sole media
    # renderer because it has the actual MediaAsset rows and destination.
    validated = TelegramVariantPayload.model_validate(payload.model_dump(mode="python"))
    try:
        validate_renderability_policy(validated)
    except TelegramPublishNeedsReview as exc:
        return [
            _issue(
                "telegram_requires_manual_media_replacement",
                "media_policy",
                str(exc),
            )
        ]
    return []


def _validate_instagram(payload: InstagramVariantPayload) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not payload.alt_text.strip():
        issues.append(
            _issue("instagram_missing_alt_text", "alt_text", "Instagram package requires alt text")
        )
    if len(payload.caption) > INSTAGRAM_CAPTION_MAX:
        issues.append(
            _issue(
                "instagram_caption_too_long",
                "caption",
                f"Caption is {len(payload.caption)}/{INSTAGRAM_CAPTION_MAX} characters",
            )
        )
    if len(payload.hashtags) > INSTAGRAM_HASHTAG_MAX:
        issues.append(
            _issue(
                "instagram_too_many_hashtags",
                "hashtags",
                f"Package has {len(payload.hashtags)}/{INSTAGRAM_HASHTAG_MAX} hashtags",
            )
        )
    issues.extend(
        _issue("instagram_empty_hashtag", f"hashtags.{index}", "Hashtags must not be empty")
        for index, hashtag in enumerate(payload.hashtags)
        if not hashtag.strip()
    )
    if len(payload.carousel) > INSTAGRAM_CAROUSEL_MAX:
        issues.append(
            _issue(
                "instagram_carousel_too_long",
                "carousel",
                f"Carousel has {len(payload.carousel)}/{INSTAGRAM_CAROUSEL_MAX} slides",
            )
        )
    if not _sequential(slide.order for slide in payload.carousel):
        issues.append(
            _issue(
                "instagram_carousel_order_invalid",
                "carousel",
                "Carousel slide order must be sequential from 1",
            )
        )
    assignments = [slide.media for slide in payload.carousel]
    if any(slide.media.order != slide.order for slide in payload.carousel):
        issues.append(
            _issue(
                "instagram_media_order_invalid",
                "carousel",
                "Carousel media order must match its slide order",
            )
        )
    if _duplicate_media_ids(assignments):
        issues.append(
            _issue(
                "instagram_duplicate_media_assignment",
                "carousel",
                "A media asset may be assigned to only one carousel slide",
            )
        )
    for index, assignment in enumerate(assignments):
        if not assignment.alt_text.strip():
            issues.append(
                _issue(
                    "instagram_missing_media_alt_text",
                    f"carousel.{index}.media.alt_text",
                    "Assigned media requires alt text",
                )
            )
        if assignment.role != "slide":
            issues.append(
                _issue(
                    "instagram_media_role_invalid",
                    f"carousel.{index}.media.role",
                    "Carousel media must use the slide role",
                )
            )
    if not payload.citations:
        issues.append(_issue("instagram_missing_citations", "citations", "Instagram copy requires a citation"))
    issues.extend(_empty_checklist_issues("instagram", payload.manual_checklist))
    return issues


def _validate_x(payload: XVariantPayload) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if payload.mode == "single" and len(payload.posts) != 1:
        issues.append(
            _issue("x_single_requires_one_post", "posts", "Single-post mode requires exactly one post")
        )
    if not _sequential(post.order for post in payload.posts):
        issues.append(_issue("x_post_order_invalid", "posts", "Post order must be sequential from 1"))

    assignments = [assignment for post in payload.posts for assignment in post.media]
    if _duplicate_media_ids(assignments):
        issues.append(
            _issue(
                "x_duplicate_media_assignment",
                "posts",
                "A media asset may be assigned only once in a thread",
            )
        )
    for post_index, post in enumerate(payload.posts):
        weighted = x_weighted_length(post.text)
        if weighted > X_POST_WEIGHT_MAX:
            issues.append(
                _issue(
                    "x_post_too_long",
                    f"posts.{post_index}.text",
                    f"Post {post.order} is {weighted}/{X_POST_WEIGHT_MAX} weighted characters",
                )
            )
        if len(post.media) > X_MEDIA_PER_POST_MAX:
            issues.append(
                _issue(
                    "x_too_many_media",
                    f"posts.{post_index}.media",
                    f"Post {post.order} has {len(post.media)}/{X_MEDIA_PER_POST_MAX} media assignments",
                )
            )
        if not _sequential(assignment.order for assignment in post.media):
            issues.append(
                _issue(
                    "x_media_order_invalid",
                    f"posts.{post_index}.media",
                    f"Post {post.order} media order must be sequential from 1",
                )
            )
        for media_index, assignment in enumerate(post.media):
            if not assignment.alt_text.strip():
                issues.append(
                    _issue(
                        "x_missing_media_alt_text",
                        f"posts.{post_index}.media.{media_index}.alt_text",
                        "Assigned media requires alt text",
                    )
                )
            if assignment.role != "post":
                issues.append(
                    _issue(
                        "x_media_role_invalid",
                        f"posts.{post_index}.media.{media_index}.role",
                        "X media must use the post role",
                    )
                )
        if not post.citations:
            issues.append(
                _issue(
                    "x_post_missing_citations",
                    f"posts.{post_index}.citations",
                    f"Post {post.order} requires a citation",
                )
            )
    issues.extend(_empty_checklist_issues("x", payload.manual_checklist))
    issues.append(
        _issue(
            "x_platform_recheck_required",
            "posts",
            "Recheck post lengths and media limits in X before manual publishing",
            severity="warning",
        )
    )
    return issues


def _validate_blog(payload: BlogVariantPayload) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not payload.citations:
        issues.append(_issue("blog_missing_citations", "citations", "Blog content requires a citation"))

    expected_sources: list[str] = []
    for citation in payload.citations:
        if citation.source_url is None:
            continue
        source_url = str(citation.source_url)
        if source_url not in expected_sources:
            expected_sources.append(source_url)
    actual_sources = [str(source) for source in payload.canonical_sources]
    if actual_sources != expected_sources:
        issues.append(
            _issue(
                "blog_canonical_sources_mismatch",
                "canonical_sources",
                "Canonical sources must match distinct cited URLs in first-citation order",
            )
        )
    if len(payload.seo_description) > BLOG_SEO_DESCRIPTION_MAX:
        issues.append(
            _issue(
                "blog_seo_description_too_long",
                "seo_description",
                f"SEO description is {len(payload.seo_description)}/{BLOG_SEO_DESCRIPTION_MAX} characters",
            )
        )
    if payload.hero_media is not None:
        if payload.hero_media.order != 1:
            issues.append(
                _issue(
                    "blog_hero_media_order_invalid",
                    "hero_media.order",
                    "Hero media order must be 1",
                )
            )
        if not payload.hero_media.alt_text.strip():
            issues.append(
                _issue(
                    "blog_missing_hero_alt_text",
                    "hero_media.alt_text",
                    "Hero media requires alt text",
                )
            )
        if payload.hero_media.role != "hero":
            issues.append(
                _issue("blog_hero_role_invalid", "hero_media.role", "Hero media must use the hero role")
            )
    issues.extend(_empty_checklist_issues("blog", payload.manual_checklist))
    return issues


_Validator = Callable[[object], list[ValidationIssue]]
PLATFORM_VALIDATORS: dict[Platform, _Validator] = {
    "telegram": _validate_telegram,
    "instagram": _validate_instagram,
    "x": _validate_x,
    "blog": _validate_blog,
}
_PLATFORM_PAYLOAD_TYPES: dict[Platform, type[BaseModel]] = {
    "telegram": TelegramVariantPayload,
    "instagram": InstagramVariantPayload,
    "x": XVariantPayload,
    "blog": BlogVariantPayload,
}


def validate_platform_payload(platform: Platform, payload: PlatformPayload) -> list[ValidationIssue]:
    validator = PLATFORM_VALIDATORS.get(platform)
    expected_type = _PLATFORM_PAYLOAD_TYPES.get(platform)
    if validator is None or expected_type is None:
        raise ValueError(f"Unsupported platform: {platform}")
    if not isinstance(payload, expected_type):
        return [
            _issue(
                "platform_payload_type_mismatch",
                "platform",
                f"Platform {platform} requires {expected_type.__name__}",
            )
        ]
    return validator(payload)
