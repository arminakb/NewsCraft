from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.generation.platform_limits import (
    BLOG_BODY_MIN,
    BLOG_EXCERPT_MAX,
    BLOG_SEO_DESCRIPTION_MAX,
    BLOG_SLUG_MAX,
    BLOG_TAG_MAX,
    BLOG_TITLE_MAX,
    INSTAGRAM_CAPTION_MAX,
    INSTAGRAM_CAROUSEL_MAX,
    INSTAGRAM_CTA_MAX,
    INSTAGRAM_HASHTAG_MAX,
    INSTAGRAM_HOOK_MAX,
    INSTAGRAM_SLIDE_BODY_MAX,
    INSTAGRAM_SLIDE_HEADLINE_MAX,
    MEDIA_ALT_TEXT_MAX,
    MEDIA_BRIEF_MAX,
    MEDIA_PROMPT_MAX,
    X_MEDIA_PER_POST_MAX,
    X_POST_WEIGHT_MAX,
    X_POSTS_MAX,
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
    issues = [
        _issue(
            f"{platform}_empty_checklist_item",
            f"manual_checklist.{index}",
            "Manual checklist items must not be empty",
        )
        for index, item in enumerate(checklist)
        if not item.strip()
    ]
    if not checklist:
        issues.append(
            _issue(
                f"{platform}_missing_manual_checklist",
                "manual_checklist",
                "Manual publishing checklist must not be empty",
            )
        )
    return issues


def _media_length_issues(platform: str, path: str, assignment: object) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    alt_text = assignment.alt_text
    if len(alt_text) > MEDIA_ALT_TEXT_MAX:
        issues.append(
            _issue(
                f"{platform}_media_alt_text_too_long",
                f"{path}.alt_text",
                f"Media alt text is {len(alt_text)}/{MEDIA_ALT_TEXT_MAX} characters",
            )
        )
    manual_brief = assignment.manual_brief
    if manual_brief is not None and len(manual_brief) > MEDIA_BRIEF_MAX:
        issues.append(
            _issue(
                f"{platform}_media_manual_brief_too_long",
                f"{path}.manual_brief",
                f"Media manual brief is {len(manual_brief)}/{MEDIA_BRIEF_MAX} characters",
            )
        )
    image_prompt = assignment.image_prompt
    if image_prompt is not None and len(image_prompt) > MEDIA_PROMPT_MAX:
        issues.append(
            _issue(
                f"{platform}_media_image_prompt_too_long",
                f"{path}.image_prompt",
                f"Media image prompt is {len(image_prompt)}/{MEDIA_PROMPT_MAX} characters",
            )
        )
    return issues


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
    if not payload.hook:
        issues.append(_issue("instagram_hook_empty", "hook", "Instagram hook must not be empty"))
    if len(payload.hook) > INSTAGRAM_HOOK_MAX:
        issues.append(
            _issue(
                "instagram_hook_too_long",
                "hook",
                f"Hook is {len(payload.hook)}/{INSTAGRAM_HOOK_MAX} characters",
            )
        )
    if not payload.caption:
        issues.append(_issue("instagram_caption_empty", "caption", "Instagram caption must not be empty"))
    if not payload.cta:
        issues.append(_issue("instagram_cta_empty", "cta", "Instagram call to action must not be empty"))
    if len(payload.cta) > INSTAGRAM_CTA_MAX:
        issues.append(
            _issue(
                "instagram_cta_too_long",
                "cta",
                f"Call to action is {len(payload.cta)}/{INSTAGRAM_CTA_MAX} characters",
            )
        )
    if not payload.alt_text.strip():
        issues.append(
            _issue("instagram_missing_alt_text", "alt_text", "Instagram package requires alt text")
        )
    if len(payload.alt_text) > MEDIA_ALT_TEXT_MAX:
        issues.append(
            _issue(
                "instagram_alt_text_too_long",
                "alt_text",
                f"Alt text is {len(payload.alt_text)}/{MEDIA_ALT_TEXT_MAX} characters",
            )
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
        slide = payload.carousel[index]
        if not slide.headline:
            issues.append(
                _issue(
                    "instagram_slide_headline_empty",
                    f"carousel.{index}.headline",
                    "Carousel slide headline must not be empty",
                )
            )
        if len(slide.headline) > INSTAGRAM_SLIDE_HEADLINE_MAX:
            issues.append(
                _issue(
                    "instagram_slide_headline_too_long",
                    f"carousel.{index}.headline",
                    f"Slide headline is {len(slide.headline)}/{INSTAGRAM_SLIDE_HEADLINE_MAX} characters",
                )
            )
        if not slide.body:
            issues.append(
                _issue(
                    "instagram_slide_body_empty",
                    f"carousel.{index}.body",
                    "Carousel slide body must not be empty",
                )
            )
        if len(slide.body) > INSTAGRAM_SLIDE_BODY_MAX:
            issues.append(
                _issue(
                    "instagram_slide_body_too_long",
                    f"carousel.{index}.body",
                    f"Slide body is {len(slide.body)}/{INSTAGRAM_SLIDE_BODY_MAX} characters",
                )
            )
        if not assignment.alt_text.strip():
            issues.append(
                _issue(
                    "instagram_missing_media_alt_text",
                    f"carousel.{index}.media.alt_text",
                    "Assigned media requires alt text",
                )
            )
        issues.extend(_media_length_issues("instagram", f"carousel.{index}.media", assignment))
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
    if not payload.posts:
        issues.append(_issue("x_posts_missing", "posts", "X package requires at least one post"))
    if len(payload.posts) > X_POSTS_MAX:
        issues.append(
            _issue(
                "x_too_many_posts",
                "posts",
                f"Package has {len(payload.posts)}/{X_POSTS_MAX} posts",
            )
        )
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
        if not post.text:
            issues.append(
                _issue("x_post_empty", f"posts.{post_index}.text", f"Post {post.order} must not be empty")
            )
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
            issues.extend(
                _media_length_issues(
                    "x",
                    f"posts.{post_index}.media.{media_index}",
                    assignment,
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
    if not payload.title:
        issues.append(_issue("blog_title_empty", "title", "Blog title must not be empty"))
    if len(payload.title) > BLOG_TITLE_MAX:
        issues.append(
            _issue(
                "blog_title_too_long",
                "title",
                f"Title is {len(payload.title)}/{BLOG_TITLE_MAX} characters",
            )
        )
    if len(payload.slug) > BLOG_SLUG_MAX:
        issues.append(
            _issue(
                "blog_slug_too_long",
                "slug",
                f"Slug is {len(payload.slug)}/{BLOG_SLUG_MAX} characters",
            )
        )
    if not payload.excerpt:
        issues.append(_issue("blog_excerpt_empty", "excerpt", "Blog excerpt must not be empty"))
    if len(payload.excerpt) > BLOG_EXCERPT_MAX:
        issues.append(
            _issue(
                "blog_excerpt_too_long",
                "excerpt",
                f"Excerpt is {len(payload.excerpt)}/{BLOG_EXCERPT_MAX} characters",
            )
        )
    if len(payload.body_markdown) < BLOG_BODY_MIN:
        issues.append(
            _issue(
                "blog_body_too_short",
                "body_markdown",
                f"Body is {len(payload.body_markdown)}/{BLOG_BODY_MIN} characters",
            )
        )
    if not payload.headings:
        issues.append(_issue("blog_headings_missing", "headings", "Blog requires at least one heading"))
    if len(payload.tags) > BLOG_TAG_MAX:
        issues.append(
            _issue(
                "blog_too_many_tags",
                "tags",
                f"Blog has {len(payload.tags)}/{BLOG_TAG_MAX} tags",
            )
        )
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
    if len(payload.seo_description) < 50:
        issues.append(
            _issue(
                "blog_seo_description_too_short",
                "seo_description",
                f"SEO description is {len(payload.seo_description)}/50 characters",
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
        issues.extend(_media_length_issues("blog", "hero_media", payload.hero_media))
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


def revision_gates_from_issues(issues: list[ValidationIssue]) -> list[dict[str, object]]:
    """Persist Release 4 validation through the Release 3 gate-shaped contract."""

    if not issues:
        return [{"gate": "platform_schema", "ok": True, "reason": None}]
    return [
        {
            "gate": issue.code,
            "ok": issue.severity != "error",
            "reason": issue.message,
        }
        for issue in issues
    ]
