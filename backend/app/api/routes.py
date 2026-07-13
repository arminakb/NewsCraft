from fastapi import APIRouter

from app.api.content import router as content_router
from app.api.content_packs import router as content_packs_router
from app.api.control import router as control_router
from app.api.diagnostics import router as diagnostics_router
from app.api.exports import router as exports_router
from app.api.generation_settings import router as generation_settings_router
from app.api.ingest import router as ingest_router
from app.api.jobs import router as jobs_router
from app.api.media import router as media_router
from app.api.sources import router as sources_router
from app.api.stories import router as stories_router
from app.api.telegram_automations import router as telegram_automations_router
from app.api.telegram_destinations import router as telegram_destinations_router
from app.api.telegram_drafts import router as telegram_drafts_router
from app.api.telegram_sources import router as telegram_sources_router

router = APIRouter()
router.include_router(sources_router)
router.include_router(stories_router)
router.include_router(ingest_router)
router.include_router(content_router)
router.include_router(content_packs_router)
router.include_router(media_router)
router.include_router(diagnostics_router)
router.include_router(exports_router)
router.include_router(jobs_router)
router.include_router(control_router)
router.include_router(telegram_sources_router)
router.include_router(telegram_destinations_router)
router.include_router(telegram_drafts_router)
router.include_router(telegram_automations_router)
router.include_router(generation_settings_router)
