from __future__ import annotations

from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    Platform,
    PlatformPayload,
    TelegramVariantPayload,
    XVariantPayload,
)


def render_platform_copy(platform: Platform, payload: PlatformPayload) -> str:
    if platform == "telegram" and isinstance(payload, TelegramVariantPayload):
        return payload.body
    if platform == "instagram" and isinstance(payload, InstagramVariantPayload):
        hashtags = " ".join(payload.hashtags)
        return "\n\n".join(part for part in (payload.hook, payload.caption, payload.cta, hashtags) if part)
    if platform == "x" and isinstance(payload, XVariantPayload):
        posts = sorted(payload.posts, key=lambda item: item.order)
        if len(posts) == 1:
            return posts[0].text
        total = len(posts)
        return "\n\n".join(f"{index}/{total} {post.text}" for index, post in enumerate(posts, start=1))
    if platform == "blog" and isinstance(payload, BlogVariantPayload):
        return payload.body_markdown
    raise ValueError(f"Platform {platform} payload type does not match")


def render_platform_markdown(platform: Platform, payload: PlatformPayload) -> str:
    title = {"telegram": "Telegram", "instagram": "Instagram", "x": "X", "blog": "Blog"}[platform]
    return f"# {title}\n\n{render_platform_copy(platform, payload)}\n"
