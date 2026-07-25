from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.api.telegram_schemas import TelegramSourceCreate, TelegramSourceOut
from app.automations.models import TelegramSourceConfig
from app.db.models import Source
from app.db.session import get_session
from app.jobs.credential_capabilities import CapabilityStatusService

router = APIRouter(prefix="/telegram/sources", tags=["telegram"])
SessionDependency = Depends(get_session)


async def _source_out(
    source: Source,
    config: TelegramSourceConfig,
    capability_status: CapabilityStatusService,
) -> TelegramSourceOut:
    state = await capability_status.get("source", source.id, "source")
    return TelegramSourceOut(
        id=source.id,
        name=source.name,
        channel_ref=config.channel_ref,
        access_mode=config.access_mode,
        language_hint=source.language_hint,
        configured=state.available,
        capability_state=state,
    )


def _source_matches(source: Source, config: TelegramSourceConfig, body: TelegramSourceCreate) -> bool:
    return (
        source.name == body.name
        and source.language_hint == body.language_hint
        and config.channel_ref == body.channel_ref
        and config.access_mode == body.access_mode
        and config.api_id_secret_ref == body.api_id_secret_ref
        and config.api_hash_secret_ref == body.api_hash_secret_ref
        and config.session_secret_ref == body.session_secret_ref
    )


@router.get("", response_model=list[TelegramSourceOut])
async def list_telegram_sources(
    session: AsyncSession = SessionDependency,
    capability_status: CapabilityStatusDependency = None,
):
    sources = list(
        await session.scalars(select(Source).where(Source.platform == "telegram_public").order_by(Source.name))
    )
    result = []
    for source in sources:
        config = await session.get(TelegramSourceConfig, source.id)
        if config is not None:
            result.append(await _source_out(source, config, capability_status))
    return result


@router.post("", response_model=TelegramSourceOut, status_code=201)
async def create_telegram_source(
    body: TelegramSourceCreate,
    session: AsyncSession = SessionDependency,
    capability_status: CapabilityStatusDependency = None,
):
    existing = await session.scalar(
        select(Source).where(
            Source.platform == "telegram_public",
            Source.telegram_username == body.channel_ref,
        )
    )
    if existing is not None:
        config = await session.get(TelegramSourceConfig, existing.id)
        if config is not None:
            if _source_matches(existing, config, body):
                return await _source_out(existing, config, capability_status)
            raise HTTPException(409, "Telegram source already exists with different configuration")

    source = Source(
        platform="telegram_public",
        name=body.name,
        telegram_username=body.channel_ref,
        source_group="telegram",
        language_hint=body.language_hint,
        default_timezone="UTC",
        active=True,
    )
    config = TelegramSourceConfig(
        access_mode=body.access_mode,
        channel_ref=body.channel_ref,
        peer_id=None,
        api_id_secret_ref=body.api_id_secret_ref,
        api_hash_secret_ref=body.api_hash_secret_ref,
        session_secret_ref=body.session_secret_ref,
    )
    try:
        async with session.begin_nested():
            session.add(source)
            await session.flush()
            config.source_id = source.id
            session.add(config)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(Source).where(
                Source.platform == "telegram_public",
                Source.telegram_username == body.channel_ref,
            )
        )
        existing_config = await session.get(TelegramSourceConfig, existing.id) if existing is not None else None
        if existing is None or existing_config is None or not _source_matches(existing, existing_config, body):
            raise HTTPException(409, "Telegram source already exists with different configuration") from None
        return await _source_out(existing, existing_config, capability_status)
    await session.commit()
    return await _source_out(source, config, capability_status)
