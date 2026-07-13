from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.model_registry import Base
from app.db.models import ContentItem, SourceItem
from app.jobs.models import AutomationControl
from app.normalization.urls import hash_value, normalize_url
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision
from app.stories.repository import (
    EvidenceKeyCollision,
    StoryRepository,
    _candidate_identity_statement,
    _choose_oldest_matching_canonical,
    _story_grouping_lock_statement,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_grouping_critical_section_uses_transaction_scoped_postgresql_advisory_lock():
    sql = str(_story_grouping_lock_statement().compile(dialect=postgresql.dialect())).upper()

    assert "PG_ADVISORY_XACT_LOCK" in sql
    assert "PG_ADVISORY_LOCK(" not in sql


def test_candidate_identity_query_deduplicates_snapshots_and_prioritizes_exact_urls():
    item = SimpleNamespace(
        canonical_url="https://example.com/report?utm_source=feed",
        published_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        sort_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
    )

    statement = _candidate_identity_statement([item])
    sql = str(statement.compile(dialect=postgresql.dialect())).upper()

    assert "SELECT DISTINCT" in sql
    assert "CASE WHEN" in sql
    assert sql.count("CASE WHEN") == 1
    assert "CANONICAL_URL_HASH" in sql
    assert "ORDER BY" in sql
    assert "ORDER BY EXACT_PRIORITY" in sql
    assert "LIMIT" in sql
    assert "STORY_EVIDENCE_SNAPSHOTS.CAPTURED_AT" not in sql


def test_title_candidate_query_uses_stable_keyset_after_each_bounded_page():
    item = SimpleNamespace(
        canonical_url="https://example.com/page-item",
        published_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        sort_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
    )
    after = (
        datetime(2026, 7, 11, 8, tzinfo=UTC),
        uuid4(),
        uuid4(),
    )

    statement = _candidate_identity_statement([item], exact_only=False, after=after)
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled).upper()

    assert "SELECT DISTINCT" in sql
    assert "OFFSET" not in sql
    assert "STORIES.CREATED_AT" in sql
    assert "STORIES.ID" in sql
    assert "CONTENT_ITEMS.ID" in sql
    assert " > " in sql
    assert "LIMIT" in sql


@pytest.mark.asyncio
async def test_pending_selection_does_not_skip_locked_rows_before_uuid_cursor():
    class RecordingSession:
        def __init__(self):
            self.statement = None

        async def scalars(self, statement):
            self.statement = statement
            return []

    session = RecordingSession()

    await StoryRepository(session).list_pending_content_items(limit=100, cursor=uuid4())

    sql = str(session.statement.compile(dialect=postgresql.dialect())).upper()
    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" not in sql


def test_page_boundary_match_selects_existing_oldest_canonical():
    older = SimpleNamespace(
        id=uuid4(),
        created_at=datetime(2026, 7, 11, 8, tzinfo=UTC),
    )
    existing_item = SimpleNamespace(
        id=uuid4(),
        title="Original title",
        canonical_url="https://example.com/report?utm_source=feed",
        published_at=datetime(2026, 7, 11, 8, tzinfo=UTC),
        sort_at=datetime(2026, 7, 11, 8, tzinfo=UTC),
    )
    next_page_item = SimpleNamespace(
        id=uuid4(),
        title="Edited title",
        canonical_url="https://example.com/report",
        published_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        sort_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
    )

    selected = _choose_oldest_matching_canonical(
        [next_page_item],
        [(older, existing_item)],
    )

    assert selected is older


@pytest.mark.asyncio
async def test_candidate_resolution_compares_older_title_match_with_newer_exact_url():
    observed_at = datetime(2026, 7, 11, 9, tzinfo=UTC)
    older_story = SimpleNamespace(
        id=uuid4(),
        status="inbox",
        superseded_by_id=None,
        created_at=observed_at - timedelta(hours=2),
    )
    newer_exact_story = SimpleNamespace(
        id=uuid4(),
        status="inbox",
        superseded_by_id=None,
        created_at=observed_at - timedelta(hours=1),
    )
    older_title_item = SimpleNamespace(
        id=uuid4(),
        title="OpenAI releases new coding agent for developers",
        canonical_url="https://older.example/agent",
        published_at=observed_at,
        sort_at=observed_at,
    )
    newer_exact_item = SimpleNamespace(
        id=uuid4(),
        title="Unrelated exact URL title",
        canonical_url="https://example.com/report",
        published_at=observed_at,
        sort_at=observed_at,
    )
    incoming = SimpleNamespace(
        id=uuid4(),
        title="OpenAI releases a coding agent for software developers",
        canonical_url="https://example.com/report?utm_source=page",
        published_at=observed_at,
        sort_at=observed_at,
    )
    exact_identity = SimpleNamespace(
        story_id=newer_exact_story.id,
        content_item_id=newer_exact_item.id,
        story_created_at=newer_exact_story.created_at,
    )
    title_identity = SimpleNamespace(
        story_id=older_story.id,
        content_item_id=older_title_item.id,
        story_created_at=older_story.created_at,
    )

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class CandidateSession:
        def __init__(self):
            self.execute_results = [[exact_identity], [title_identity]]
            self.scalar_results = [
                [newer_exact_item],
                [newer_exact_story],
                [newer_exact_item],
                [older_title_item],
                [older_story],
                [older_title_item],
            ]

        async def execute(self, statement):
            return Result(self.execute_results.pop(0))

        async def scalars(self, statement):
            return self.scalar_results.pop(0)

    selected = await StoryRepository(CandidateSession())._matching_active_canonical([incoming])

    assert selected is older_story


@pytest.mark.asyncio
async def test_candidate_lock_refreshes_and_revalidates_changed_content_item():
    observed_at = datetime(2026, 7, 11, 9, tzinfo=UTC)
    story = SimpleNamespace(
        id=uuid4(),
        status="inbox",
        superseded_by_id=None,
        created_at=observed_at - timedelta(hours=1),
    )
    content_item_id = uuid4()
    observed_match = SimpleNamespace(
        id=content_item_id,
        title="OpenAI releases new coding agent for developers",
        canonical_url="https://candidate.example/agent",
        published_at=observed_at,
        sort_at=observed_at,
    )
    refreshed_nonmatch = SimpleNamespace(
        id=content_item_id,
        title="Global chip sales rise",
        canonical_url="https://changed.example/chips",
        published_at=observed_at - timedelta(days=30),
        sort_at=observed_at - timedelta(days=30),
    )
    incoming = SimpleNamespace(
        id=uuid4(),
        title="OpenAI releases a coding agent for software developers",
        canonical_url="https://incoming.example/agent",
        published_at=observed_at,
        sort_at=observed_at,
    )
    identity = SimpleNamespace(
        story_id=story.id,
        content_item_id=content_item_id,
        story_created_at=story.created_at,
    )

    class CandidateSession:
        def __init__(self):
            self.results = [[observed_match], [story], [refreshed_nonmatch]]
            self.statements = []

        async def scalars(self, statement):
            self.statements.append(statement)
            return self.results.pop(0)

    session = CandidateSession()

    selected = await StoryRepository(session)._lock_matching_candidate([incoming], [identity])

    assert selected is None
    locking_content_query = session.statements[-1]
    assert locking_content_query.get_execution_options()["populate_existing"] is True


@pytest_asyncio.fixture(scope="module")
async def story_engine() -> AsyncIterator[AsyncEngine]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_name = make_url(TEST_DATABASE_URL).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing destructive PostgreSQL tests unless the database name ends in '_test'")
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(story_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    table_names = [story_engine.dialect.identifier_preparer.quote(table.name) for table in Base.metadata.sorted_tables]
    async with story_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
        await connection.execute(insert(AutomationControl).values(id="global", global_pause=False, dry_run=False))
    factory = async_sessionmaker(story_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


async def content_item(
    session: AsyncSession,
    *,
    title: str,
    content_text: str,
    canonical_url: str,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
) -> ContentItem:
    observed_at = published_at or datetime(2026, 7, 11, 8, tzinfo=UTC)
    row = ContentItem(
        item_type="article",
        canonical_url=canonical_url,
        canonical_url_hash=hash_value(normalize_url(canonical_url)),
        title=title,
        content_text=content_text,
        authors=["Reporter"],
        published_at=observed_at,
        sort_at=observed_at,
        date_parse_status="parsed",
        language_code="en",
    )
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    await session.flush()
    return row


async def provisional_story(
    session: AsyncSession,
    *,
    title: str,
    snapshot_texts: list[str],
    evidence_key: str | None = None,
) -> tuple[Story, ContentItem, list[StoryEvidenceSnapshot], list[StoryRevision]]:
    item = await content_item(
        session,
        title=title,
        content_text=snapshot_texts[-1],
        canonical_url=f"https://example.com/{uuid4()}",
    )
    story = Story(title=title, status="telegram_provisional", primary_language="en")
    session.add(story)
    await session.flush()
    snapshots = []
    revisions = []
    for index, value in enumerate(snapshot_texts, start=1):
        digest = sha256(value.encode("utf-8")).hexdigest()
        snapshot = StoryEvidenceSnapshot(
            story_id=story.id,
            content_item_id=item.id,
            evidence_key=evidence_key or f"content-item:{item.id}:{digest}",
            source_url=item.canonical_url,
            title=title,
            content_text=value,
            authors=["Reporter"],
            published_at=item.published_at,
            content_sha256=digest,
            snapshot_metadata={"edit": index},
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC) + timedelta(minutes=index),
        )
        session.add(snapshot)
        await session.flush()
        revision = StoryRevision(
            story_id=story.id,
            parent_revision_id=revisions[-1].id if revisions else None,
            revision_number=index,
            narrative=value,
            facts=[],
            disagreements=[],
            angles=[],
            citations=[],
            created_by="telegram_source_edit" if revisions else "telegram_capture",
        )
        session.add(revision)
        await session.flush()
        snapshots.append(snapshot)
        revisions.append(revision)
    return story, item, snapshots, revisions


@pytest.mark.asyncio
async def test_group_content_items_reuses_story_and_captures_one_snapshot_per_hash(db_session: AsyncSession):
    first_captured_at = datetime(2026, 7, 11, 8, tzinfo=UTC)
    first = await content_item(
        db_session,
        title="OpenAI agent launch details",
        canonical_url="https://a.example/agent",
        content_text="Evidence A",
        created_at=first_captured_at,
    )
    second = await content_item(
        db_session,
        title="OpenAI agent launch report",
        canonical_url="https://b.example/agent",
        content_text="Evidence B",
        created_at=first_captured_at + timedelta(minutes=1),
    )
    repository = StoryRepository(db_session)

    story = await repository.group_content_items([first.id, second.id])
    replay = await repository.group_content_items([first.id, second.id])

    assert replay.id == story.id
    snapshots = await repository.list_evidence(story.id)
    assert [snapshot.content_text for snapshot in snapshots] == ["Evidence A", "Evidence B"]
    assert len({snapshot.content_sha256 for snapshot in snapshots}) == 2


@pytest.mark.asyncio
async def test_related_items_on_separate_pages_reuse_existing_active_canonical(db_session: AsyncSession):
    first_captured_at = datetime(2026, 7, 11, 8, tzinfo=UTC)
    first = await content_item(
        db_session,
        title="Original report",
        canonical_url="https://example.com/report?utm_source=feed",
        content_text="Evidence A",
        created_at=first_captured_at,
    )
    second = await content_item(
        db_session,
        title="Updated report",
        canonical_url="https://example.com/report",
        content_text="Evidence B",
        created_at=first_captured_at + timedelta(minutes=1),
    )
    repository = StoryRepository(db_session)

    page_one_story = await repository.group_content_items([first.id])
    page_two_story = await repository.group_content_items([second.id])

    assert page_two_story.id == page_one_story.id
    assert [row.content_text for row in await repository.list_evidence(page_one_story.id)] == [
        "Evidence A",
        "Evidence B",
    ]


@pytest.mark.asyncio
async def test_grouping_prefers_older_title_match_over_newer_exact_url(db_session: AsyncSession):
    observed_at = datetime(2026, 7, 11, 9, tzinfo=UTC)

    async def canonical_with_evidence(
        *,
        title: str,
        canonical_url: str,
        content_text: str,
        created_at: datetime,
    ):
        item = await content_item(
            db_session,
            title=title,
            canonical_url=canonical_url,
            content_text=content_text,
            published_at=observed_at,
        )
        story = Story(
            title=title,
            status="inbox",
            primary_language="en",
            created_at=created_at,
        )
        db_session.add(story)
        await db_session.flush()
        digest = sha256(content_text.encode("utf-8")).hexdigest()
        db_session.add(
            StoryEvidenceSnapshot(
                story_id=story.id,
                content_item_id=item.id,
                evidence_key=f"content-item:{item.id}:{digest}",
                source_url=item.canonical_url,
                title=item.title,
                content_text=content_text,
                authors=[],
                published_at=item.published_at,
                content_sha256=digest,
                snapshot_metadata={},
                captured_at=created_at,
            )
        )
        await db_session.flush()
        return story

    older = await canonical_with_evidence(
        title="OpenAI releases new coding agent for developers",
        canonical_url="https://older.example/agent",
        content_text="Older related evidence",
        created_at=observed_at - timedelta(hours=2),
    )
    await canonical_with_evidence(
        title="Unrelated exact URL title",
        canonical_url="https://example.com/report",
        content_text="Newer exact evidence",
        created_at=observed_at - timedelta(hours=1),
    )
    incoming = await content_item(
        db_session,
        title="OpenAI releases a coding agent for software developers",
        canonical_url="https://example.com/report?utm_source=page",
        content_text="Incoming evidence",
        published_at=observed_at,
    )

    selected = await StoryRepository(db_session).group_content_items([incoming.id])

    assert selected.id == older.id


@pytest.mark.asyncio
async def test_concurrent_related_disjoint_items_return_one_canonical(
    db_session: AsyncSession,
    story_engine: AsyncEngine,
):
    first = await content_item(
        db_session,
        title="Concurrent report A",
        canonical_url="https://example.com/concurrent?utm_source=first",
        content_text="Evidence A",
    )
    second = await content_item(
        db_session,
        title="Concurrent report B",
        canonical_url="https://example.com/concurrent",
        content_text="Evidence B",
    )
    first_id, second_id = first.id, second.id
    await db_session.commit()
    factory = async_sessionmaker(story_engine, expire_on_commit=False)

    async def group_one(content_item_id):
        async with factory() as session:
            async with session.begin():
                story = await StoryRepository(session).group_content_items([content_item_id])
                return story.id

    first_story_id, second_story_id = await asyncio.gather(
        group_one(first_id),
        group_one(second_id),
    )

    assert first_story_id == second_story_id


@pytest.mark.asyncio
async def test_exact_url_candidate_is_not_drowned_by_duplicate_snapshots(
    db_session: AsyncSession,
):
    unrelated_item = await content_item(
        db_session,
        title="Unrelated archive",
        canonical_url="https://example.com/archive",
        content_text="Archive",
    )
    unrelated_story = Story(title="Unrelated archive", status="inbox", primary_language="en")
    db_session.add(unrelated_story)
    await db_session.flush()
    duplicate_snapshots = []
    for index in range(501):
        value = f"Archive evidence {index}"
        digest = sha256(value.encode("utf-8")).hexdigest()
        duplicate_snapshots.append(
            StoryEvidenceSnapshot(
                story_id=unrelated_story.id,
                content_item_id=unrelated_item.id,
                evidence_key=f"content-item:{unrelated_item.id}:{digest}",
                source_url=unrelated_item.canonical_url,
                title=unrelated_item.title,
                content_text=value,
                authors=[],
                published_at=unrelated_item.published_at,
                content_sha256=digest,
                snapshot_metadata={"index": index},
                captured_at=datetime(2026, 7, 11, 8, tzinfo=UTC) + timedelta(seconds=index),
            )
        )
    db_session.add_all(duplicate_snapshots)

    exact_item = await content_item(
        db_session,
        title="Exact report",
        canonical_url="https://example.com/exact",
        content_text="Exact canonical evidence",
    )
    exact_story = Story(title="Exact report", status="inbox", primary_language="en")
    db_session.add(exact_story)
    await db_session.flush()
    exact_digest = sha256(exact_item.content_text.encode("utf-8")).hexdigest()
    db_session.add(
        StoryEvidenceSnapshot(
            story_id=exact_story.id,
            content_item_id=exact_item.id,
            evidence_key=f"content-item:{exact_item.id}:{exact_digest}",
            source_url=exact_item.canonical_url,
            title=exact_item.title,
            content_text=exact_item.content_text,
            authors=[],
            published_at=exact_item.published_at,
            content_sha256=exact_digest,
            snapshot_metadata={},
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    related = await content_item(
        db_session,
        title="Different exact report title",
        canonical_url="https://example.com/exact?utm_campaign=page-two",
        content_text="Page two evidence",
    )
    await db_session.flush()

    selected = await StoryRepository(db_session).group_content_items([related.id])

    assert selected.id == exact_story.id


@pytest.mark.asyncio
async def test_title_match_after_five_hundred_older_unrelated_candidates_is_reused(
    db_session: AsyncSession,
):
    base_time = datetime(2026, 7, 11, 8, tzinfo=UTC)
    for index in range(500):
        unrelated_item = await content_item(
            db_session,
            title=f"Unrelated archive topic {index}",
            canonical_url=f"https://example.com/archive/{index}",
            content_text=f"Archive {index}",
            published_at=base_time,
        )
        unrelated_story = Story(
            title=f"Unrelated {index}",
            status="inbox",
            primary_language="en",
            created_at=base_time + timedelta(microseconds=index),
        )
        db_session.add(unrelated_story)
        await db_session.flush()
        digest = sha256(unrelated_item.content_text.encode("utf-8")).hexdigest()
        db_session.add(
            StoryEvidenceSnapshot(
                story_id=unrelated_story.id,
                content_item_id=unrelated_item.id,
                evidence_key=f"content-item:{unrelated_item.id}:{digest}",
                source_url=unrelated_item.canonical_url,
                title=unrelated_item.title,
                content_text=unrelated_item.content_text,
                authors=[],
                published_at=base_time,
                content_sha256=digest,
                snapshot_metadata={},
                captured_at=base_time,
            )
        )

    related_item = await content_item(
        db_session,
        title="OpenAI releases new coding agent for developers",
        canonical_url="https://candidate.example/agent",
        content_text="Canonical related evidence",
        published_at=base_time + timedelta(hours=1),
    )
    related_story = Story(
        title="Related canonical",
        status="inbox",
        primary_language="en",
        created_at=base_time + timedelta(seconds=1),
    )
    db_session.add(related_story)
    await db_session.flush()
    related_digest = sha256(related_item.content_text.encode("utf-8")).hexdigest()
    db_session.add(
        StoryEvidenceSnapshot(
            story_id=related_story.id,
            content_item_id=related_item.id,
            evidence_key=f"content-item:{related_item.id}:{related_digest}",
            source_url=related_item.canonical_url,
            title=related_item.title,
            content_text=related_item.content_text,
            authors=[],
            published_at=related_item.published_at,
            content_sha256=related_digest,
            snapshot_metadata={},
            captured_at=base_time + timedelta(hours=1),
        )
    )
    page_item = await content_item(
        db_session,
        title="OpenAI releases a coding agent for software developers",
        canonical_url="https://page.example/agent",
        content_text="Page evidence",
        published_at=base_time + timedelta(hours=2),
    )
    await db_session.flush()

    selected = await StoryRepository(db_session).group_content_items([page_item.id])

    assert selected.id == related_story.id


@pytest.mark.asyncio
async def test_grouping_copies_all_provisional_snapshots_without_moving_originals(db_session: AsyncSession):
    first = await provisional_story(
        db_session,
        title="OpenAI agent launch",
        snapshot_texts=["Evidence A", "Evidence A corrected"],
    )
    second = await provisional_story(
        db_session,
        title="OpenAI agent launch details",
        snapshot_texts=["Evidence B"],
    )
    original_snapshots = [*first[2], *second[2]]
    original_snapshot_ids = {row.id for row in original_snapshots}
    original_revision_ids = {row.id for row in [*first[3], *second[3]]}

    repository = StoryRepository(db_session)
    canonical = await repository.group_content_items([first[1].id, second[1].id])
    replay = await repository.group_content_items([first[1].id, second[1].id])
    copied = await repository.list_evidence(canonical.id)

    assert replay.id == canonical.id
    assert canonical.id not in {first[0].id, second[0].id}
    assert {row.content_sha256 for row in copied} == {row.content_sha256 for row in original_snapshots}
    assert {row.evidence_snapshot_id for row in copied}.isdisjoint(original_snapshot_ids)
    assert first[0].superseded_by_id == canonical.id
    assert second[0].superseded_by_id == canonical.id
    persisted_revision_ids = set(
        await db_session.scalars(select(StoryRevision.id).where(StoryRevision.id.in_(original_revision_ids)))
    )
    assert persisted_revision_ids == original_revision_ids


@pytest.mark.asyncio
async def test_grouping_preserves_release_two_dispatch_revision_ids(db_session: AsyncSession):
    from tests.postgres.test_telegram_process_handler import seed_dispatch

    first_dispatch, _, shared = await seed_dispatch(db_session, route_name="grouping-one")
    second_dispatch, _, _ = await seed_dispatch(
        db_session,
        route_name="grouping-two",
        shared=shared,
    )
    first_source_item = await db_session.get(SourceItem, first_dispatch.source_item_id)
    second_source_item = await db_session.get(SourceItem, second_dispatch.source_item_id)
    original_dispatch_revision_ids = {
        first_dispatch.story_revision_id,
        second_dispatch.story_revision_id,
    }

    await StoryRepository(db_session).group_content_items(
        [first_source_item.content_item_id, second_source_item.content_item_id]
    )

    assert {
        first_dispatch.story_revision_id,
        second_dispatch.story_revision_id,
    } == original_dispatch_revision_ids
    assert set(
        await db_session.scalars(
            select(StoryRevision.id).where(StoryRevision.id.in_(original_dispatch_revision_ids))
        )
    ) == original_dispatch_revision_ids


@pytest.mark.asyncio
async def test_grouping_deduplicates_equal_snapshot_payloads_by_evidence_key(db_session: AsyncSession):
    shared_key = f"operator-text:{sha256(b'Shared evidence').hexdigest()}"
    first = await provisional_story(
        db_session,
        title="Shared story",
        snapshot_texts=["Shared evidence"],
        evidence_key=shared_key,
    )
    second = await provisional_story(
        db_session,
        title="Shared story",
        snapshot_texts=["Shared evidence"],
        evidence_key=shared_key,
    )
    for snapshot in [first[2][0], second[2][0]]:
        snapshot.content_item_id = first[1].id
        snapshot.source_url = None
        snapshot.snapshot_metadata = {"operator": True}
        snapshot.captured_at = datetime(2026, 7, 11, 9, tzinfo=UTC)
    await db_session.flush()

    canonical = await StoryRepository(db_session).group_content_items([first[1].id, second[1].id])
    copied = await StoryRepository(db_session).list_evidence(canonical.id)

    assert [row.evidence_key for row in copied].count(shared_key) == 1
    assert first[0].superseded_by_id == canonical.id
    assert second[0].superseded_by_id == canonical.id


@pytest.mark.asyncio
async def test_unequal_evidence_key_collision_does_not_supersede(db_session: AsyncSession):
    reused_key = f"operator-text:{sha256(b'Original evidence').hexdigest()}"
    first = await provisional_story(
        db_session,
        title="Collision story",
        snapshot_texts=["Original evidence"],
        evidence_key=reused_key,
    )
    second = await provisional_story(
        db_session,
        title="Collision story",
        snapshot_texts=["Different payload"],
        evidence_key=reused_key,
    )
    for snapshot in [first[2][0], second[2][0]]:
        snapshot.content_item_id = first[1].id
        snapshot.source_url = None
        snapshot.snapshot_metadata = {"operator": True}
        snapshot.captured_at = datetime(2026, 7, 11, 9, tzinfo=UTC)
    await db_session.flush()

    with pytest.raises(EvidenceKeyCollision, match="same evidence_key has different snapshot payload"):
        await StoryRepository(db_session).group_content_items([first[1].id, second[1].id])

    assert first[0].superseded_by_id is None
    assert second[0].superseded_by_id is None
