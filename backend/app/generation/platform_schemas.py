from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

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
    X_POSTS_MAX,
)
from app.generation.telegram_schema import TelegramVariantContent
from app.research.schemas import CitationRef

type Platform = Literal["telegram", "instagram", "x", "blog"]


def _reject_url_userinfo(urls: list[HttpUrl | None]) -> None:
    if any(url is not None and (url.username is not None or url.password is not None) for url in urls):
        raise ValueError("Manual platform URLs cannot contain userinfo")


class MediaAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_asset_id: UUID | None
    role: Literal["hero", "slide", "post", "inline"]
    order: int = Field(ge=1)
    alt_text: str = Field(min_length=1, max_length=MEDIA_ALT_TEXT_MAX)
    manual_brief: str | None = Field(default=None, max_length=MEDIA_BRIEF_MAX)
    image_prompt: str | None = Field(default=None, max_length=MEDIA_PROMPT_MAX)


class InstagramSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1, le=INSTAGRAM_CAROUSEL_MAX)
    headline: str = Field(min_length=1, max_length=INSTAGRAM_SLIDE_HEADLINE_MAX)
    body: str = Field(min_length=1, max_length=INSTAGRAM_SLIDE_BODY_MAX)
    media: MediaAssignment


class TelegramVariantPayload(TelegramVariantContent):
    """Named compatibility view over the exact Release 2 stored mapping."""


class InstagramVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook: str = Field(min_length=1, max_length=INSTAGRAM_HOOK_MAX)
    caption: str = Field(min_length=1, max_length=INSTAGRAM_CAPTION_MAX)
    cta: str = Field(min_length=1, max_length=INSTAGRAM_CTA_MAX)
    hashtags: list[str] = Field(max_length=INSTAGRAM_HASHTAG_MAX)
    alt_text: str = Field(min_length=1, max_length=MEDIA_ALT_TEXT_MAX)
    carousel: list[InstagramSlide] = Field(max_length=INSTAGRAM_CAROUSEL_MAX)
    citations: list[CitationRef] = Field(min_length=1)
    manual_checklist: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_citation_userinfo(self):
        _reject_url_userinfo([citation.source_url for citation in self.citations])
        return self


class XPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1, le=X_POSTS_MAX)
    text: str = Field(min_length=1)
    media: list[MediaAssignment] = Field(max_length=X_MEDIA_PER_POST_MAX)
    citations: list[CitationRef] = Field(min_length=1)


class XVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "thread"]
    posts: list[XPost] = Field(min_length=1, max_length=X_POSTS_MAX)
    link_strategy: Literal["first_post", "last_post", "each_post", "no_link"]
    manual_checklist: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_citation_userinfo(self):
        _reject_url_userinfo(
            [citation.source_url for post in self.posts for citation in post.citations]
        )
        return self


class BlogVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=BLOG_TITLE_MAX)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=BLOG_SLUG_MAX)
    excerpt: str = Field(min_length=1, max_length=BLOG_EXCERPT_MAX)
    body_markdown: str = Field(min_length=BLOG_BODY_MIN)
    headings: list[str] = Field(min_length=1)
    citations: list[CitationRef] = Field(default_factory=list)
    tags: list[str] = Field(max_length=BLOG_TAG_MAX)
    seo_description: str = Field(min_length=50, max_length=BLOG_SEO_DESCRIPTION_MAX)
    hero_media: MediaAssignment | None
    canonical_sources: list[HttpUrl] = Field(default_factory=list)
    manual_checklist: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_url_userinfo(self):
        _reject_url_userinfo(
            [*[citation.source_url for citation in self.citations], *self.canonical_sources]
        )
        return self


type PlatformPayload = (
    TelegramVariantPayload | InstagramVariantPayload | XVariantPayload | BlogVariantPayload
)


class InstagramEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["instagram"]
    content: InstagramVariantPayload


class XEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["x"]
    content: XVariantPayload


class BlogEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["blog"]
    content: BlogVariantPayload


type ManualPlatformEditPayload = Annotated[
    InstagramEditPayload | XEditPayload | BlogEditPayload,
    Field(discriminator="platform"),
]


class ManualPlatformEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision_id: UUID
    base_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: ManualPlatformEditPayload
    evidence_map: list[CitationRef] = Field(min_length=1)
    edit_note: str = Field(min_length=1, max_length=500)
