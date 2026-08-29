from __future__ import annotations

from types import SimpleNamespace

from app.research.handlers import budget_termination_metadata
from app.research.schemas import ResearchBudget


def _usage(**overrides: int) -> SimpleNamespace:
    values = dict(
        model_calls=1,
        input_tokens=100,
        output_tokens=50,
        queries=0,
        pages=0,
        fetched_characters=10,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _budget() -> ResearchBudget:
    return ResearchBudget(
        max_model_calls=6,
        max_input_tokens=10_000,
        max_output_tokens=2_000,
        max_cost_usd=1,
        max_queries=3,
        max_results_per_query=3,
        max_pages=5,
        max_elapsed_seconds=120,
        max_total_chars=100_000,
    )


def test_completed_research_reports_completion_without_budget_reason():
    metadata = budget_termination_metadata(_budget(), _usage(queries=1, pages=2), 45_000)
    assert metadata["termination_reason"] == "completed"
    assert metadata["queries_executed"] == 1
    assert metadata["pages_inspected"] == 2
    assert metadata["elapsed_ms"] == 45_000


def test_exhausted_dimensions_are_named_in_the_stop_reason():
    usage = _usage(queries=3, pages=5, output_tokens=2_000, model_calls=6)
    metadata = budget_termination_metadata(_budget(), usage, 121_000)
    assert metadata["termination_reason"] == (
        "budget_exhausted:model_call_budget,output_token_budget,page_budget,query_budget,time_budget"
    )


def test_time_budget_alone_is_reported():
    metadata = budget_termination_metadata(_budget(), _usage(), 120_000)
    assert metadata["termination_reason"] == "budget_exhausted:time_budget"
