from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from app.stories.evidence import EvidenceInput, capture_evidence


def test_content_item_evidence_uses_locked_content_item_key():
    content_item_id = uuid4()
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id=content_item_id,
            title="Title",
            content_text="Body",
            source_url="https://example.com/source",
            authors=["Reporter"],
            published_at=datetime(2026, 7, 11, tzinfo=UTC),
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    changed = capture_evidence(replace(evidence.input, content_text="Changed body"))

    assert evidence.content_sha256 == sha256(b"Body").hexdigest()
    assert evidence.evidence_key == f"content-item:{content_item_id}:{evidence.content_sha256}"
    assert evidence.content_sha256 != changed.content_sha256
    assert evidence.evidence_key != changed.evidence_key


def test_operator_text_evidence_allows_truthful_null_source_url():
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id=None,
            title="Operator interview",
            content_text="Direct notes supplied by the operator.",
            source_url=None,
            authors=["Operator"],
            published_at=None,
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )

    assert evidence.source_url is None
    assert evidence.evidence_key == f"operator-text:{evidence.content_sha256}"


def test_url_evidence_key_includes_normalized_url_and_content_hash():
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id=None,
            title="Fetched report",
            content_text="First immutable version",
            source_url="https://example.com/report?utm_source=test",
            authors=[],
            published_at=None,
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    changed = capture_evidence(replace(evidence.input, content_text="Changed immutable version"))

    assert evidence.evidence_key == f"url:https://example.com/report:{evidence.content_sha256}"
    assert changed.evidence_key == f"url:https://example.com/report:{changed.content_sha256}"
    assert changed.evidence_key != evidence.evidence_key
