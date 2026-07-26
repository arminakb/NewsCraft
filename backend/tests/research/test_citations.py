import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.research.citations import CitationIntegrityError, resolve_candidate_brief, validate_citations
from app.research.schemas import (
    CandidateCitation,
    CandidateClaim,
    CandidateResearchBrief,
    CitationRef,
    Claim,
    DiscoveredSourcePayload,
)
from app.stories.evidence import EvidenceRecord, build_evidence_key


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _record(*, body: str = "alpha beta", url: str | None = "https://example.com/a") -> EvidenceRecord:
    digest = _digest(body)
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


def _candidate(key: str, *, body: str = "alpha beta") -> CandidateCitation:
    return CandidateCitation(evidence_key=key, locator="chars:0-5", excerpt_sha256=_digest(body[0:5]))


def _discovered(*, url: str = "https://new.example/story", body: str = "discovered body") -> DiscoveredSourcePayload:
    digest = _digest(body)
    return DiscoveredSourcePayload(
        evidence_key=build_evidence_key(content_item_id=None, source_url=url, content_sha256=digest),
        url=url,
        title="Story",
        publisher="Publisher",
        published_at=None,
        retrieved_at=datetime.now(UTC),
        content_text=body,
        content_sha256=digest,
        extraction_status="ok",
    )


def test_discovered_payload_rejects_orm_id_extra_and_changed_url_or_body_key() -> None:
    source = _discovered()
    with pytest.raises(ValidationError):
        DiscoveredSourcePayload.model_validate({**source.model_dump(), "id": uuid4()})
    with pytest.raises(ValidationError):
        DiscoveredSourcePayload.model_validate({**source.model_dump(), "url": "https://changed.example/story"})
    with pytest.raises(ValidationError):
        DiscoveredSourcePayload.model_validate({**source.model_dump(), "content_text": "changed body"})
    with pytest.raises(ValidationError):
        CandidateResearchBrief.model_validate(
            {
                "summary": "summary",
                "verified_facts": [
                    {
                        "text": "claim",
                        "citations": [
                            {**_candidate(source.evidence_key).model_dump(), "evidence_snapshot_id": str(uuid4())}
                        ],
                    }
                ],
                "disagreements": [],
                "missing_information": [],
                "suggested_angles": [],
                "discovered_evidence_keys": [],
            }
        )


def test_resolve_operator_null_source_and_handler_supplied_snapshot_id() -> None:
    record = _record(url=None)
    persisted_id = uuid4()
    materialized = replace(record, evidence_snapshot_id=persisted_id)
    candidate = CandidateResearchBrief(
        summary="summary",
        verified_facts=[CandidateClaim(text="claim", citations=[_candidate(record.evidence_key)])],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[record.evidence_key],
    )
    resolved = resolve_candidate_brief(
        candidate,
        {record.evidence_key: materialized},
        {record.evidence_key: persisted_id},
    )

    assert resolved.verified_facts[0].citations[0] == CitationRef(
        evidence_snapshot_id=persisted_id,
        evidence_key=record.evidence_key,
        source_url=None,
        locator="chars:0-5",
        excerpt_sha256=_digest("alpha"),
    )


def test_resolve_discovered_source_and_locator_boundaries() -> None:
    source = _discovered(body="abcdef")
    persisted_id = uuid4()
    record = _record(body=source.content_text, url=str(source.url))
    record = replace(record, evidence_snapshot_id=persisted_id)
    candidate = CandidateResearchBrief(
        summary="summary",
        verified_facts=[
            CandidateClaim(
                text="claim",
                citations=[
                    CandidateCitation(
                        evidence_key=source.evidence_key,
                        locator="chars:0-6",
                        excerpt_sha256=_digest("abcdef"),
                    )
                ],
            )
        ],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[source.evidence_key],
    )
    resolved = resolve_candidate_brief(candidate, {source.evidence_key: record}, {source.evidence_key: persisted_id})
    assert resolved.verified_facts[0].citations[0].evidence_snapshot_id == persisted_id

    for locator in ("chars:1-1", "chars:0-7"):
        bad = candidate.model_copy(
            update={
                "verified_facts": [
                    CandidateClaim(
                        text="claim",
                        citations=[
                            _candidate(source.evidence_key, body="abcdef").model_copy(update={"locator": locator})
                        ],
                    )
                ]
            }
        )
        with pytest.raises(CitationIntegrityError):
            resolve_candidate_brief(bad, {source.evidence_key: record}, {source.evidence_key: persisted_id})


def test_resolve_rejects_unknown_key_and_changed_body_excerpt_checksum() -> None:
    record = _record()
    with pytest.raises(CitationIntegrityError, match="unknown evidence key"):
        resolve_candidate_brief(
            CandidateResearchBrief(
                summary="summary",
                verified_facts=[CandidateClaim(text="claim", citations=[_candidate("operator-text:" + "0" * 64)])],
                disagreements=[],
                missing_information=[],
                suggested_angles=[],
                discovered_evidence_keys=[],
            ),
            {record.evidence_key: record},
            {},
        )
    with pytest.raises(CitationIntegrityError, match="excerpt checksum"):
        resolve_candidate_brief(
            CandidateResearchBrief(
                summary="summary",
                verified_facts=[
                    CandidateClaim(text="claim", citations=[_candidate(record.evidence_key, body="changed")])
                ],
                disagreements=[],
                missing_information=[],
                suggested_angles=[],
                discovered_evidence_keys=[],
            ),
            {record.evidence_key: record},
            {},
        )


def test_discovery_citation_must_be_declared_by_candidate() -> None:
    record = _record()
    candidate = CandidateResearchBrief(
        summary="summary",
        verified_facts=[CandidateClaim(text="claim", citations=[_candidate(record.evidence_key)])],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[],
    )

    with pytest.raises(CitationIntegrityError, match="unknown evidence key"):
        resolve_candidate_brief(
            candidate,
            {record.evidence_key: record},
            {record.evidence_key: record.evidence_snapshot_id},
        )


def test_discovered_keys_and_resolved_ids_must_be_unique() -> None:
    first = _record(body="first body", url="https://first.example/a")
    second = _record(body="second body", url="https://second.example/b")
    shared_id = uuid4()
    evidence = {first.evidence_key: first, second.evidence_key: second}

    duplicate_key = CandidateResearchBrief(
        summary="summary",
        verified_facts=[],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[first.evidence_key, first.evidence_key],
    )
    with pytest.raises(CitationIntegrityError, match="duplicate discovered evidence key"):
        resolve_candidate_brief(duplicate_key, evidence, {first.evidence_key: first.evidence_snapshot_id})

    duplicate_id = duplicate_key.model_copy(
        update={"discovered_evidence_keys": [first.evidence_key, second.evidence_key]}
    )
    with pytest.raises(CitationIntegrityError, match="duplicate discovered source ID"):
        resolve_candidate_brief(
            duplicate_id,
            evidence,
            {first.evidence_key: shared_id, second.evidence_key: shared_id},
        )


def test_resolved_unicode_url_citation_validates_against_snapshot() -> None:
    record = _record(url="https://www.bücher.de/a")
    candidate = CandidateResearchBrief(
        summary="summary",
        verified_facts=[CandidateClaim(text="claim", citations=[_candidate(record.evidence_key)])],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[],
    )
    brief = resolve_candidate_brief(candidate, {record.evidence_key: record}, {})

    assert (
        validate_citations(
            brief.verified_facts,
            {record.evidence_snapshot_id: record},
        )
        == brief.verified_facts
    )


def test_unicode_path_and_query_match_already_percent_encoded_citation_url() -> None:
    record = _record(url="https://www.bücher.de/خبر مهم?q=سلام دنیا")
    candidate = CandidateResearchBrief(
        summary="summary",
        verified_facts=[CandidateClaim(text="claim", citations=[_candidate(record.evidence_key)])],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[],
    )
    brief = resolve_candidate_brief(candidate, {record.evidence_key: record}, {})
    resolved_citation = brief.verified_facts[0].citations[0]

    assert "%" in str(resolved_citation.source_url)
    assert (
        validate_citations(
            brief.verified_facts,
            {record.evidence_snapshot_id: record},
        )
        == brief.verified_facts
    )

    already_encoded = resolved_citation.model_copy(update={"source_url": str(resolved_citation.source_url)})
    assert validate_citations(
        [Claim(text="claim", citations=[already_encoded])],
        {record.evidence_snapshot_id: record},
    )


def test_validate_citations_detects_snapshot_key_url_locator_and_hash_mismatches() -> None:
    record = _record()
    citation = CitationRef(
        evidence_snapshot_id=record.evidence_snapshot_id,
        evidence_key=record.evidence_key,
        source_url=record.source_url,
        locator="chars:0-5",
        excerpt_sha256=_digest("alpha"),
    )
    validate_citations([Claim(text="claim", citations=[citation])], {record.evidence_snapshot_id: record})

    mutations = [
        ({}, {}),
        ({"evidence_key": "operator-text:" + "0" * 64}, {record.evidence_snapshot_id: record}),
        ({"source_url": "https://wrong.example/x"}, {record.evidence_snapshot_id: record}),
        ({"locator": "chars:0-99"}, {record.evidence_snapshot_id: record}),
        ({"excerpt_sha256": "0" * 64}, {record.evidence_snapshot_id: record}),
    ]
    for update, snapshots in mutations:
        with pytest.raises(CitationIntegrityError):
            validate_citations(
                [Claim(text="claim", citations=[citation.model_copy(update=update)])],
                snapshots,
            )


def test_claims_require_at_least_one_citation() -> None:
    with pytest.raises(ValidationError):
        CandidateClaim(text="unsupported", citations=[])
    with pytest.raises(ValidationError):
        Claim(text="unsupported", citations=[])
