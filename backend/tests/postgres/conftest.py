from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.model_registry import Base
from app.jobs.models import AutomationControl

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    database_name = make_url(TEST_DATABASE_URL).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing destructive PostgreSQL tests unless the database name ends in '_test'")


@pytest_asyncio.fixture(scope="session")
async def postgres_engine() -> AsyncIterator[AsyncEngine]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def reset_postgres(postgres_engine: AsyncEngine) -> AsyncIterator[None]:
    table_names = [
        postgres_engine.dialect.identifier_preparer.quote(table.name) for table in Base.metadata.sorted_tables
    ]
    async with postgres_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
        await connection.execute(insert(AutomationControl).values(id="global", global_pause=False, dry_run=False))
    yield


@pytest.fixture
def session_factory(postgres_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(postgres_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def job_repository(db_session: AsyncSession):
    from app.jobs.repository import JobRepository

    return JobRepository(db_session)
