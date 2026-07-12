from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import ContentItem, ContentProductionRun, MediaAsset, VisualBrief


@dataclass(frozen=True)
class ImageGenerationResponse:
    status: str
    provider_result: dict
    error_message: str | None = None


class ImageGenerationProvider(Protocol):
    provider_name: str

    async def request_image(self, prompt: str, style: str | None = None) -> ImageGenerationResponse:
        ...


class NullImageGenerationProvider:
    provider_name = "none"

    async def request_image(self, prompt: str, style: str | None = None) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            status="pending",
            provider_result={},
            error_message="no_image_generation_provider_configured",
        )


class MediaResolverService:
    def __init__(self, session, image_provider: ImageGenerationProvider | None = None):
        self.session = session
        self.image_provider = image_provider or NullImageGenerationProvider()

    async def resolve(
        self,
        *,
        run: ContentProductionRun,
        item: ContentItem,
        media_assets: list[MediaAsset] | None = None,
        command_id: uuid.UUID | None = None,
    ) -> VisualBrief:
        brief_id = artifact_id(command_id or run.id, "visual_brief")

        async def create() -> VisualBrief:
            repository = ContentProductionRepository(self.session)
            if run.state == WorkflowState.QUALITY_PASSED.value:
                await repository.transition_run(run, WorkflowState.MEDIA_RESOLVING, current_step="media_resolver")

            selected = select_media_asset(item, media_assets or [])
            if selected:
                brief = VisualBrief(
                    id=brief_id,
                    production_run_id=run.id,
                    status="selected",
                    selected_media_asset_id=selected.id,
                    needs_generation=False,
                    visual_prompt=None,
                    visual_style=None,
                    provider_name=None,
                    provider_request_json={},
                    provider_result_json={},
                )
                self.session.add(brief)
                await self.session.flush()
                await repository.transition_run(run, WorkflowState.MEDIA_READY, current_step="media_resolver")
                return brief

            prompt = build_visual_prompt(item)
            response = await self.image_provider.request_image(prompt, style="editorial news image")
            brief = VisualBrief(
                id=brief_id,
                production_run_id=run.id,
                status=response.status,
                selected_media_asset_id=None,
                needs_generation=True,
                visual_prompt=prompt,
                visual_style="editorial news image",
                provider_name=self.image_provider.provider_name,
                provider_request_json={"prompt": prompt, "style": "editorial news image"},
                provider_result_json=response.provider_result,
                error_message=response.error_message,
            )
            self.session.add(brief)
            await self.session.flush()
            await repository.transition_run(run, WorkflowState.IMAGE_GENERATION_PENDING, current_step="media_resolver")
            if response.status == "generated":
                await repository.transition_run(run, WorkflowState.IMAGE_GENERATING, current_step="media_resolver")
                await repository.transition_run(run, WorkflowState.IMAGE_READY, current_step="media_resolver")
            return brief

        return await create_or_get_artifact(self.session, VisualBrief, brief_id, create)


def select_media_asset(item: ContentItem, media_assets: list[MediaAsset]) -> MediaAsset | None:
    if item.primary_media and _is_suitable(item.primary_media):
        return item.primary_media
    if item.primary_image_id:
        for asset in media_assets:
            if asset.id == item.primary_image_id and _is_suitable(asset):
                return asset
    suitable = [asset for asset in media_assets if _is_suitable(asset)]
    return suitable[0] if suitable else None


def build_visual_prompt(item: ContentItem) -> str:
    title = item.title or "news story"
    source_context = item.summary or item.content_text or ""
    context = source_context[:240].strip()
    return (
        "Create an editorial Telegram image concept for this news item. "
        f"Title: {title}. Context: {context}. "
        "Avoid logos, fake screenshots, unsupported people, and misleading claims."
    )


def _is_suitable(asset: MediaAsset) -> bool:
    if asset.kind != "image":
        return False
    if asset.media_quality in {"low", "tracking"}:
        return False
    if asset.fetch_status in {"failed", "missing"}:
        return False
    if asset.width is not None and asset.width < 320:
        return False
    if asset.height is not None and asset.height < 180:
        return False
    return True
