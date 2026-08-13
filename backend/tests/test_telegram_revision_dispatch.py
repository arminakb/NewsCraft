from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.generation.models import PlatformVariant
from app.publishing.telegram import draft_publication, scheduling, service_contracts


class _FakeVariant:
    def __init__(self, platform: str) -> None:
        self.platform = platform


class _FakeRevision:
    def __init__(
        self,
        *,
        variant_id: UUID,
        parent_revision_id: UUID | None = None,
    ) -> None:
        self.id = uuid4()
        self.platform_variant_id = variant_id
        self.parent_revision_id = parent_revision_id


class _FakeSession:
    def __init__(
        self,
        *,
        variant: _FakeVariant | None,
        revisions: dict[UUID, _FakeRevision] | None = None,
        dispatches: dict[UUID, object] | None = None,
    ) -> None:
        self.variant = variant
        self.revisions = revisions or {}
        self.dispatches = dispatches or {}
        self.get_calls: list[tuple[str, Any, dict[str, Any]]] = []
        self.scalar_revision_ids: list[UUID] = []
        self._walk_cursor: list[UUID] = []

    async def get(self, model: Any, ident: Any, **options: Any) -> Any:
        self.get_calls.append((model.__name__, ident, options))
        if model is PlatformVariant:
            return self.variant
        return self.revisions.get(ident)

    async def scalar(self, statement: Any) -> Any:
        # The walk always queries the revision it is currently standing on; the
        # caller pushes that id before invoking the statement.
        revision_id = self._walk_cursor.pop(0)
        self.scalar_revision_ids.append(revision_id)
        return self.dispatches.get(revision_id)

    def expect_walk(self, *revision_ids: UUID) -> None:
        self._walk_cursor = list(revision_ids)


@pytest.mark.asyncio
async def test_revision_dispatch_is_one_shared_implementation() -> None:
    assert draft_publication.revision_dispatch is service_contracts.revision_dispatch
    assert scheduling._revision_dispatch is service_contracts.revision_dispatch


@pytest.mark.asyncio
async def test_revision_dispatch_rejects_non_telegram_variants() -> None:
    variant_id = uuid4()
    revision = _FakeRevision(variant_id=variant_id)
    session = _FakeSession(variant=_FakeVariant("mastodon"))

    assert await service_contracts.revision_dispatch(session, revision) is None
    assert session.scalar_revision_ids == []


@pytest.mark.asyncio
async def test_revision_dispatch_rejects_a_missing_variant() -> None:
    revision = _FakeRevision(variant_id=uuid4())
    session = _FakeSession(variant=None)

    assert await service_contracts.revision_dispatch(session, revision) is None
    assert session.scalar_revision_ids == []


@pytest.mark.asyncio
async def test_revision_dispatch_walks_ancestry_with_fresh_reads() -> None:
    variant_id = uuid4()
    parent = _FakeRevision(variant_id=variant_id)
    child = _FakeRevision(variant_id=variant_id, parent_revision_id=parent.id)
    dispatch = object()
    session = _FakeSession(
        variant=_FakeVariant("telegram"),
        revisions={parent.id: parent},
        dispatches={parent.id: dispatch},
    )
    session.expect_walk(child.id, parent.id)

    assert await service_contracts.revision_dispatch(session, child) is dispatch
    assert session.scalar_revision_ids == [child.id, parent.id]
    # Every read must bypass a stale identity-mapped row, on both entry points.
    assert [options for _, _, options in session.get_calls] == [
        {"populate_existing": True},
        {"populate_existing": True},
    ]


@pytest.mark.asyncio
async def test_revision_dispatch_stops_on_a_parent_cycle() -> None:
    variant_id = uuid4()
    first = _FakeRevision(variant_id=variant_id)
    second = _FakeRevision(variant_id=variant_id, parent_revision_id=first.id)
    first.parent_revision_id = second.id
    session = _FakeSession(
        variant=_FakeVariant("telegram"),
        revisions={first.id: first, second.id: second},
    )
    session.expect_walk(second.id, first.id)

    assert await service_contracts.revision_dispatch(session, second) is None
