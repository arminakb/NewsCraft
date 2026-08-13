"""The row-level coverage state and the coverage facet counts share one rule.

Both SQL sites once spelled the completeness thresholds out separately, so a
change to one silently made a page's coverage badges disagree with the coverage
facet totals rendered next to them. These tests fail if the two statements stop
being generated from ``_completeness_criteria`` / ``_active_story_criteria``, or
if either drifts from the canonical Python rule in app.research.completeness.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.articles import (
    _completeness_criteria,
    _coverage_facet_statement,
    _coverage_state_expression,
    _story_completeness_subquery,
)
from app.research.completeness import MIN_BODY_CHARACTERS, MIN_INDEPENDENT_SOURCES


def _sql(element) -> str:
    compiled = element.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return str(compiled)


def test_completeness_criteria_track_the_canonical_python_thresholds() -> None:
    clauses = [_sql(clause) for clause in _completeness_criteria(_story_completeness_subquery())]

    assert clauses[0].endswith(f">= {MIN_INDEPENDENT_SOURCES}")
    assert clauses[1].endswith(f">= {MIN_BODY_CHARACTERS}")
    assert "has_primary" in clauses[2]


def test_row_state_and_facet_counts_apply_the_same_completeness_criteria() -> None:
    row_sql = _sql(select(_coverage_state_expression()))
    facet_sql = _sql(_coverage_facet_statement())

    for clause in (_sql(clause) for clause in _completeness_criteria(_story_completeness_subquery())):
        assert clause in row_sql
        assert clause in facet_sql


def test_row_state_and_facet_counts_apply_the_same_active_story_criteria() -> None:
    row_sql = _sql(select(_coverage_state_expression()))
    facet_sql = _sql(_coverage_facet_statement())

    assert row_sql.count("superseded_by_id IS NULL") == 2
    assert facet_sql.count("superseded_by_id IS NULL") == 2
