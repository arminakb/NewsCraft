from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.research.completeness import CompletenessEvidence, evaluate_completeness
from app.research.schemas import CompletenessReport, ResearchBudget
from app.stories.evidence import EvidenceRecord, build_evidence_key


def _record(*, url: str | None, body: str) -> EvidenceRecord:
    digest = __import__("hashlib").sha256(body.encode()).hexdigest()
    return EvidenceRecord(
        evidence_key=build_evidence_key(content_item_id=None, source_url=url, content_sha256=digest),
        evidence_snapshot_id=uuid4(),
        content_item_id=None,
        title=None,
        content_text=body,
        content_sha256=digest,
        source_url=url,
        authors=(),
        published_at=None,
        captured_at=datetime.now(UTC),
    )


def test_incomplete_report_has_exact_score_and_ordered_reasons() -> None:
    report = evaluate_completeness(
        [CompletenessEvidence.from_record(_record(url=None, body="short"), is_primary=False)],
        contradictions=["conflict"],
    )

    assert report == CompletenessReport(
        complete=False,
        score=10,
        reasons=[
            "fewer_than_two_independent_sources",
            "insufficient_body_text",
            "missing_primary_evidence",
            "unresolved_contradictions",
        ],
        independent_source_count=0,
        body_character_count=5,
        has_primary_evidence=False,
    )


def test_complete_report_counts_normalized_registrable_hosts_and_nonwhitespace() -> None:
    body = "a" * 800
    report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(
                _record(url="https://news.example.co.uk/a?utm_source=x", body=body), is_primary=True
            ),
            CompletenessEvidence.from_record(_record(url="https://other.org/b", body=" b ")),
            CompletenessEvidence.from_record(_record(url="https://sub.example.co.uk/c", body=" c ")),
        ]
    )

    assert report.complete is True
    assert report.score == 100
    assert report.reasons == []
    assert report.independent_source_count == 2
    assert report.body_character_count == 802
    assert report.has_primary_evidence is True


def test_anonymous_operator_text_does_not_manufacture_independent_source_identity() -> None:
    report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(_record(url=None, body="a" * 400), is_primary=True),
            CompletenessEvidence.from_record(_record(url=None, body="b" * 400)),
        ]
    )

    assert report.independent_source_count == 0
    assert report.complete is False
    assert report.reasons == ["fewer_than_two_independent_sources"]
    assert report.score == 70


def test_truthful_url_identity_cannot_be_split_by_caller_labels() -> None:
    report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(
                _record(url="https://news.example.com/a", body="a" * 400),
                source_identity="First label",
                is_primary=True,
            ),
            CompletenessEvidence.from_record(
                _record(url="https://blog.example.com/b", body="b" * 400),
                source_identity="Second label",
            ),
        ]
    )

    assert report.independent_source_count == 1
    assert report.complete is False
    assert report.reasons == ["fewer_than_two_independent_sources"]


def test_offline_psl_uses_private_domains_and_multilevel_public_suffixes() -> None:
    private_report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(
                _record(url="https://foo.blogspot.com/a", body="a" * 400), is_primary=True
            ),
            CompletenessEvidence.from_record(_record(url="https://bar.blogspot.com/b", body="b" * 400)),
        ]
    )
    public_report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(
                _record(url="https://news.example.co.uk/a", body="a" * 400), is_primary=True
            ),
            CompletenessEvidence.from_record(_record(url="https://blog.example.co.uk/b", body="b" * 400)),
        ]
    )

    assert private_report.independent_source_count == 2
    assert private_report.complete is True
    assert public_report.independent_source_count == 1
    assert public_report.complete is False


def test_unicode_and_punycode_hosts_are_one_independent_source() -> None:
    report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(
                _record(url="https://www.bücher.de/a", body="a" * 400), is_primary=True
            ),
            CompletenessEvidence.from_record(
                _record(url="https://www.xn--bcher-kva.de/b", body="b" * 400)
            ),
        ]
    )

    assert report.independent_source_count == 1
    assert report.complete is False
    assert report.reasons == ["fewer_than_two_independent_sources"]


def test_idna2008_sharp_s_and_punycode_hosts_are_one_independent_source() -> None:
    report = evaluate_completeness(
        [
            CompletenessEvidence.from_record(
                _record(url="https://faß.de/a", body="a" * 400), is_primary=True
            ),
            CompletenessEvidence.from_record(
                _record(url="https://xn--fa-hia.de/b", body="b" * 400)
            ),
        ]
    )

    assert report.independent_source_count == 1
    assert report.complete is False
    assert report.reasons == ["fewer_than_two_independent_sources"]


def test_completeness_and_budget_schemas_are_strict_bounded_and_frozen() -> None:
    budget = ResearchBudget()
    assert budget.max_model_calls == 6
    assert budget.max_cost_usd.as_tuple().exponent == -2
    with pytest.raises(ValidationError):
        ResearchBudget(max_queries=0)
    with pytest.raises(ValidationError):
        ResearchBudget(extra_setting=True)
    with pytest.raises(ValidationError):
        CompletenessReport(
            complete=False,
            score=101,
            reasons=[],
            independent_source_count=0,
            body_character_count=0,
            has_primary_evidence=False,
        )
    with pytest.raises(ValidationError):
        CompletenessReport(
            complete=False,
            score=0,
            reasons=[],
            independent_source_count=0,
            body_character_count=0,
            has_primary_evidence=False,
            surprise=True,
        )
    with pytest.raises(ValidationError):
        budget.max_queries = 8
