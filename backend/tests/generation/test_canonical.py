from uuid import uuid4

import pytest


def test_canonical_validation_rejects_unknown_citation():
    from app.generation.canonical import CanonicalStoryOutput, validate_canonical_output
    from app.research import CitationIntegrityError
    from app.research.schemas import CitationRef, Claim

    output = CanonicalStoryOutput(
        headline="Grounded headline",
        narrative="A sufficiently long canonical narrative grounded in the supplied evidence only.",
        facts=[
            Claim(
                text="A claim",
                citations=[
                    CitationRef(
                        evidence_key="missing",
                        evidence_snapshot_id=uuid4(),
                        source_url=None,
                        locator="chars:0-1",
                        excerpt_sha256="0" * 64,
                    )
                ],
            )
        ],
        disagreements=[],
        angles=[],
        missing_information=[],
    )
    with pytest.raises(CitationIntegrityError):
        validate_canonical_output(output, {})
