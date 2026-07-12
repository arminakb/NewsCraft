from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlsplit

import idna
import tldextract

from app.research.schemas import CompletenessReason, CompletenessReport

_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


class EvidenceRecordCompatible(Protocol):
    evidence_key: str
    content_text: str
    source_url: str | None


@dataclass(frozen=True, slots=True)
class CompletenessEvidence:
    """Editorial metadata layered over immutable evidence without changing EvidenceRecord.

    Callers must explicitly select primary evidence. ``source_identity`` is for
    evidence without a truthful URL (for example, an operator or wire source).
    """

    evidence_key: str
    content_text: str
    source_url: str | None
    source_identity: str | None = None
    is_primary: bool = False

    @classmethod
    def from_record(
        cls,
        record: EvidenceRecordCompatible,
        *,
        source_identity: str | None = None,
        is_primary: bool = False,
    ) -> CompletenessEvidence:
        return cls(
            evidence_key=record.evidence_key,
            content_text=record.content_text,
            source_url=record.source_url,
            source_identity=source_identity,
            is_primary=is_primary,
        )


def _registrable_host(url: str) -> str | None:
    try:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return None
    if not host:
        return None
    try:
        return str(ip_address(host))
    except ValueError:
        pass
    try:
        host = idna.encode(host, uts46=True).decode("ascii").lower()
    except idna.IDNAError:
        return None
    extracted = _TLD_EXTRACT(host)
    return extracted.top_domain_under_public_suffix or host


def _source_identity(value: CompletenessEvidence) -> str | None:
    host = _registrable_host(value.source_url) if value.source_url else None
    if host:
        return f"host:{host}"
    identity = value.source_identity.strip().casefold() if value.source_identity else ""
    return f"source:{identity}" if identity else None


def evaluate_completeness(
    evidence: Sequence[CompletenessEvidence | EvidenceRecordCompatible],
    contradictions: Sequence[str] = (),
) -> CompletenessReport:
    values = [
        value if isinstance(value, CompletenessEvidence) else CompletenessEvidence.from_record(value)
        for value in evidence
    ]
    source_count = len({identity for value in values if (identity := _source_identity(value)) is not None})
    body_character_count = sum(sum(not char.isspace() for char in value.content_text) for value in values)
    has_primary = any(value.is_primary for value in values)

    reasons: list[CompletenessReason] = []
    score = 100
    if source_count < 2:
        reasons.append("fewer_than_two_independent_sources")
        score -= 30
    if body_character_count < 800:
        reasons.append("insufficient_body_text")
        score -= 25
    if not has_primary:
        reasons.append("missing_primary_evidence")
        score -= 20
    if contradictions:
        reasons.append("unresolved_contradictions")
        score -= 15

    return CompletenessReport(
        complete=not reasons,
        score=max(0, min(100, score)),
        reasons=reasons,
        independent_source_count=source_count,
        body_character_count=body_character_count,
        has_primary_evidence=has_primary,
    )
