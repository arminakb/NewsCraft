"""The SQL coverage rule must read the persisted canonical identity, never re-derive it."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects import postgresql

from app.api.articles import _story_completeness_subquery
from app.research.completeness import snapshot_is_primary, snapshot_source_identity, source_identity_token
from app.stories.models import StoryEvidenceSnapshot, _snapshot_identity_default, _snapshot_primary_default


class _StubDefaultContext:
    def __init__(self, parameters: dict[str, Any]) -> None:
        self._parameters = parameters

    def get_current_parameters(self) -> dict[str, Any]:
        return self._parameters


def test_subdomains_of_one_registrable_domain_share_an_identity() -> None:
    assert source_identity_token("https://a.example.com/one") == source_identity_token("https://b.example.com/two")
    assert source_identity_token("https://a.example.com/one") == "host:example.com"
    assert source_identity_token("https://EXAMPLE.com:8443/x") == "host:example.com"
    assert source_identity_token("https://user:pass@example.com/x") == "host:example.com"
    assert source_identity_token("https://bücher.example/x") == "host:xn--bcher-kva.example"
    assert source_identity_token(None, "  Wire Desk ") == "source:wire desk"
    assert source_identity_token(None, None) is None
    assert source_identity_token(None, 7) is None


def test_snapshot_helpers_read_snapshot_metadata_the_way_the_report_does() -> None:
    assert snapshot_source_identity(None, {"source_label": "Wire Desk"}) == "source:wire desk"
    assert snapshot_source_identity("https://a.example.com/x", {"source_label": "Wire"}) == "host:example.com"
    assert snapshot_source_identity(None, None) is None
    assert snapshot_is_primary({"is_primary": "yes"}) is True
    assert snapshot_is_primary({"is_primary": True}) is True
    assert snapshot_is_primary({"is_primary": False}) is False
    assert snapshot_is_primary({}) is False
    assert snapshot_is_primary(None) is False


def test_snapshot_columns_are_populated_by_the_canonical_rule() -> None:
    columns = StoryEvidenceSnapshot.__table__.c
    assert columns.source_identity.default is not None
    assert columns.source_identity.default.arg is _snapshot_identity_default
    assert columns.is_primary.default is not None
    assert columns.is_primary.default.arg is _snapshot_primary_default

    context = _StubDefaultContext(
        {"source_url": "https://b.example.com/two", "snapshot_metadata": {"is_primary": "yes"}}
    )
    assert _snapshot_identity_default(context) == "host:example.com"
    assert _snapshot_primary_default(context) is True
    empty = _StubDefaultContext({})
    assert _snapshot_identity_default(empty) is None
    assert _snapshot_primary_default(empty) is False


def test_completeness_subquery_reads_persisted_columns() -> None:
    compiled = str(_story_completeness_subquery().select().compile(dialect=postgresql.dialect()))
    assert "split_part" not in compiled
    assert "source_identity" in compiled
    assert "bool_or(story_evidence_snapshots.is_primary)" in compiled
