from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        # Only public API mutations are capability-gated. Worker continuations
        # and scheduler jobs own separate sessions and must remain replayable.
        session.info["enforce_api_capability_gate"] = True
        yield session
