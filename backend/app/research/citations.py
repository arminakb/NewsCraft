from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import idna
from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.normalization.urls import normalize_url
from app.research.schemas import CandidateClaim, CandidateResearchBrief, CitationRef, Claim, ResearchBrief
from app.stories.evidence import EvidenceRecord

_LOCATOR_PATTERN = re.compile(r"chars:(\d+)-(\d+)")
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class CitationIntegrityError(ValueError):
    pass


def resolve_locator(content_text: str, locator: str) -> str:
    match = _LOCATOR_PATTERN.fullmatch(locator)
    if match is None:
        raise CitationIntegrityError("citation locator must use chars:<start>-<end>")
    start, end = (int(value) for value in match.groups())
    if not 0 <= start < end <= len(content_text):
        raise CitationIntegrityError("citation locator is outside evidence content")
    return content_text[start:end]


def _resolve_candidate_claim(value: CandidateClaim, evidence_by_key: Mapping[str, EvidenceRecord]) -> Claim:
    citations: list[CitationRef] = []
    for candidate in value.citations:
        evidence = evidence_by_key.get(candidate.evidence_key)
        if evidence is None:
            raise CitationIntegrityError(f"unknown evidence key: {candidate.evidence_key}")
        if evidence.evidence_key != candidate.evidence_key:
            raise CitationIntegrityError("candidate evidence key does not match snapshot")
        excerpt = resolve_locator(evidence.content_text, candidate.locator)
        digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        if digest != candidate.excerpt_sha256:
            raise CitationIntegrityError("citation excerpt checksum does not match evidence")
        citations.append(
            CitationRef(
                evidence_key=evidence.evidence_key,
                evidence_snapshot_id=evidence.evidence_snapshot_id,
                source_url=evidence.source_url,
                locator=candidate.locator,
                excerpt_sha256=candidate.excerpt_sha256,
            )
        )
    return Claim(text=value.text, citations=citations)


def resolve_candidate_brief(
    candidate: CandidateResearchBrief,
    evidence_by_key: Mapping[str, EvidenceRecord],
    discovered_source_ids: Mapping[str, UUID],
) -> ResearchBrief:
    candidate_keys = candidate.discovered_evidence_keys
    if len(candidate_keys) != len(set(candidate_keys)):
        raise CitationIntegrityError("duplicate discovered evidence key")

    for key in candidate_keys:
        if key not in evidence_by_key:
            raise CitationIntegrityError(f"unknown evidence key: {key}")
        if key not in discovered_source_ids:
            raise CitationIntegrityError(f"unknown discovered evidence key: {key}")

    source_ids = [discovered_source_ids[key] for key in candidate_keys]
    if len(source_ids) != len(set(source_ids)):
        raise CitationIntegrityError("duplicate discovered source ID")

    request_keys = set(evidence_by_key).difference(discovered_source_ids)
    allowed_keys = request_keys.union(candidate_keys)
    allowed_evidence = {key: evidence_by_key[key] for key in allowed_keys}

    return ResearchBrief(
        summary=candidate.summary,
        verified_facts=[_resolve_candidate_claim(value, allowed_evidence) for value in candidate.verified_facts],
        disagreements=[_resolve_candidate_claim(value, allowed_evidence) for value in candidate.disagreements],
        missing_information=candidate.missing_information,
        suggested_angles=candidate.suggested_angles,
        discovered_source_ids=source_ids,
    )


def _canonicalize_citation_url(value: str) -> str:
    try:
        serialized = str(_HTTP_URL_ADAPTER.validate_python(value))
        normalized = normalize_url(serialized)
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            raise ValueError
        port = parts.port
        host = parts.hostname.rstrip(".").lower()
        try:
            canonical_host = str(ip_address(host))
            if ":" in canonical_host:
                canonical_host = f"[{canonical_host}]"
        except ValueError:
            canonical_host = idna.encode(host, uts46=True).decode("ascii").lower()
        netloc = canonical_host if port is None else f"{canonical_host}:{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    except (ValidationError, UnicodeError, ValueError, idna.IDNAError) as exc:
        raise CitationIntegrityError("invalid citation URL") from exc


def validate_citations(claims: Sequence[Claim], snapshots: Mapping[UUID, EvidenceRecord]) -> list[Claim]:
    for claim in claims:
        if not claim.citations:
            raise CitationIntegrityError("claim has no citations")
        for citation in claim.citations:
            snapshot = snapshots.get(citation.evidence_snapshot_id)
            if snapshot is None:
                raise CitationIntegrityError(f"unknown evidence snapshot: {citation.evidence_snapshot_id}")
            if citation.evidence_key != snapshot.evidence_key:
                raise CitationIntegrityError("citation evidence key does not match snapshot")
            citation_url = _canonicalize_citation_url(str(citation.source_url)) if citation.source_url else None
            snapshot_url = _canonicalize_citation_url(snapshot.source_url) if snapshot.source_url else None
            if citation_url != snapshot_url:
                raise CitationIntegrityError("citation URL does not match evidence snapshot")
            excerpt = resolve_locator(snapshot.content_text, citation.locator)
            if hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != citation.excerpt_sha256:
                raise CitationIntegrityError("citation excerpt hash does not match evidence")
    return list(claims)
