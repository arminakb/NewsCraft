from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = BACKEND_ROOT / ".venv/bin/alembic"


def _alembic(revision: str) -> None:
    environment = {**os.environ, "DATABASE_URL": str(TEST_DATABASE_URL)}
    subprocess.run(
        [str(ALEMBIC), "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        timeout=120,
    )


async def _seed_release_two_dispatches() -> list[UUID]:
    engine = create_async_engine(str(TEST_DATABASE_URL), poolclass=NullPool)
    ids = [
        UUID("10000000-0000-4000-8000-000000000001"),
        UUID("10000000-0000-4000-8000-000000000002"),
        UUID("10000000-0000-4000-8000-000000000003"),
        UUID("10000000-0000-4000-8000-000000000004"),
    ]
    source_id = UUID("20000000-0000-4000-8000-000000000001")
    source_item_id = UUID("30000000-0000-4000-8000-000000000001")
    story_id = UUID("40000000-0000-4000-8000-000000000001")
    revision_id = UUID("50000000-0000-4000-8000-000000000001")
    brand_id = UUID("60000000-0000-4000-8000-000000000001")
    template_id = UUID("70000000-0000-4000-8000-000000000001")
    template_version_id = UUID("80000000-0000-4000-8000-000000000001")
    provider_id = UUID("90000000-0000-4000-8000-000000000001")
    destination_id = UUID("a0000000-0000-4000-8000-000000000001")
    route_id = UUID("b0000000-0000-4000-8000-000000000001")
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM automation_dispatches"))
        await connection.execute(
            text(
                "INSERT INTO sources (id, platform, name, source_group) "
                "VALUES (:id, 'telegram', 'migration-source', 'migration') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": source_id},
        )
        await connection.execute(
            text("INSERT INTO source_items (id, source_id) VALUES (:id, :source_id) ON CONFLICT (id) DO NOTHING"),
            {"id": source_item_id, "source_id": source_id},
        )
        await connection.execute(
            text("INSERT INTO stories (id, title) VALUES (:id, 'Migration story') ON CONFLICT (id) DO NOTHING"),
            {"id": story_id},
        )
        await connection.execute(
            text(
                "INSERT INTO story_revisions (id, story_id, revision_number, narrative, created_by) "
                "VALUES (:id, :story_id, 1, 'Migration narrative', 'test') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": revision_id, "story_id": story_id},
        )
        await connection.execute(
            text(
                "INSERT INTO brand_profiles (id, name, output_language, tone) "
                "VALUES (:id, 'migration-brand', 'en', 'neutral') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": brand_id},
        )
        await connection.execute(
            text(
                "INSERT INTO prompt_templates (id, purpose_key, name) "
                "VALUES (:id, 'migration-purpose', 'migration-template') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": template_id},
        )
        await connection.execute(
            text(
                "INSERT INTO prompt_template_versions "
                "(id, prompt_template_id, version, system_template, user_template, "
                "output_schema_version, checksum_sha256) "
                "VALUES (:id, :template_id, 1, 'system', 'user', '1', :checksum) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": template_version_id, "template_id": template_id, "checksum": "0" * 64},
        )
        await connection.execute(
            text(
                "INSERT INTO ai_provider_profiles (id, name, provider_type) "
                "VALUES (:id, 'migration-provider', 'fake') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": provider_id},
        )
        await connection.execute(
            text(
                "INSERT INTO destinations (id, name, platform, target_ref, secret_ref) "
                "VALUES (:id, 'migration-destination', 'telegram', '@migration', 'MIGRATION_TOKEN') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": destination_id},
        )
        await connection.execute(
            text(
                "INSERT INTO automation_routes "
                "(id, name, source_id, destination_id, brand_profile_id, prompt_template_version_id, "
                "ai_provider_profile_id) VALUES (:id, 'migration-route', :source_id, :destination_id, "
                ":brand_id, :template_version_id, :provider_id) ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": route_id,
                "source_id": source_id,
                "destination_id": destination_id,
                "brand_id": brand_id,
                "template_version_id": template_version_id,
                "provider_id": provider_id,
            },
        )
        inserted = [
            (ids[3], datetime(2026, 1, 3, tzinfo=UTC)),
            (ids[2], datetime(2026, 1, 2, tzinfo=UTC)),
            (ids[0], datetime(2026, 1, 1, tzinfo=UTC)),
            (ids[1], datetime(2026, 1, 2, tzinfo=UTC)),
        ]
        for position, (dispatch_id, created_at) in enumerate(inserted, start=1):
            await connection.execute(
                text(
                    "INSERT INTO automation_dispatches "
                    "(id, route_id, source_item_id, story_revision_id, source_key, source_fingerprint, "
                    "source_message_ids, dispatch_kind, created_at) VALUES (:id, :route_id, :source_item_id, "
                    ":revision_id, :source_key, :fingerprint, ARRAY[:message_id]::bigint[], 'live', :created_at)"
                ),
                {
                    "id": dispatch_id,
                    "route_id": route_id,
                    "source_item_id": source_item_id,
                    "revision_id": revision_id,
                    "source_key": f"migration-{position}",
                    "fingerprint": f"fingerprint-{position}",
                    "message_id": position,
                    "created_at": created_at,
                },
            )
        # Force new heap tuples in an order unrelated to canonical chronology.
        for dispatch_id in (ids[1], ids[3], ids[0]):
            await connection.execute(
                text("UPDATE automation_dispatches SET updated_at = clock_timestamp() WHERE id = :id"),
                {"id": dispatch_id},
            )
    await engine.dispose()
    return ids


async def _verify_upgrade(ids: list[UUID]) -> None:
    engine = create_async_engine(str(TEST_DATABASE_URL), poolclass=NullPool)
    async with engine.begin() as connection:
        rows = list(
            await connection.execute(
                text(
                    "SELECT id, creation_sequence FROM automation_dispatches "
                    "WHERE id = ANY(:ids) ORDER BY creation_sequence"
                ),
                {"ids": ids},
            )
        )
        assert [row.id for row in rows] == ids
        assert [row.creation_sequence for row in rows] == [1, 2, 3, 4]
        next_value = await connection.scalar(
            text(
                "INSERT INTO automation_dispatches "
                "(id, route_id, source_item_id, story_revision_id, source_key, "
                "source_fingerprint, source_message_ids, dispatch_kind) "
                "SELECT :new_id, route_id, source_item_id, story_revision_id, "
                "'migration-next', 'fingerprint-next', ARRAY[99]::bigint[], 'live' "
                "FROM automation_dispatches WHERE id = :existing_id "
                "RETURNING creation_sequence"
            ),
            {
                "new_id": UUID("10000000-0000-4000-8000-000000000005"),
                "existing_id": ids[0],
            },
        )
        assert next_value > rows[-1].creation_sequence
        owned = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_depend d "
                "JOIN pg_class sequence ON sequence.oid = d.objid "
                "JOIN pg_class table_relation ON table_relation.oid = d.refobjid "
                "JOIN pg_attribute attribute ON attribute.attrelid = table_relation.oid "
                "AND attribute.attnum = d.refobjsubid "
                "WHERE sequence.relname = 'automation_dispatch_creation_sequence_seq' "
                "AND table_relation.relname = 'automation_dispatches' "
                "AND attribute.attname = 'creation_sequence' AND d.deptype = 'a'"
            )
        )
        assert owned == 1
    await engine.dispose()


def test_upgrade_backfills_canonical_chronology_and_advances_db_sequence():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for the dispatch migration test")
    database_name = make_url(TEST_DATABASE_URL).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing destructive migration test unless database ends in '_test'")

    environment = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        [str(ALEMBIC), "downgrade", "0006_telegram_automation_vertical"],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        timeout=120,
    )
    try:
        ids = asyncio.run(_seed_release_two_dispatches())
        _alembic("0007_dispatch_creation_sequence")
        asyncio.run(_verify_upgrade(ids))
    finally:
        _alembic("head")
