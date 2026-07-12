from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.db.models import ArticleExtractionResult, ContentItem, WebEnrichmentResult

TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)
MAX_PRIMARY_TEXT = 6000
MAX_EXCERPT_TEXT = 1600
MAX_ENRICHMENT_TEXT = 700


def evaluate_enrichment_relevance(
    *,
    title: str | None,
    source_url: str | None,
    source_name: str | None,
    findings: list[dict],
) -> list[dict]:
    target_title = _normalize(title or "")
    target_terms = _terms(title or "")
    target_domain = _domain(source_url)
    source_signal = _normalize(source_name or target_domain or "")
    original = _canonical_url(source_url)
    assessed: list[dict] = []

    for finding in findings:
        row = dict(finding)
        url = str(row.get("url") or "")
        result_title = str(row.get("title") or "")
        snippet = str(row.get("snippet") or "")
        combined = _normalize(f"{result_title} {snippet}")
        result_terms = _terms(f"{result_title} {snippet}")
        result_domain = _domain(url)
        matched: list[str] = []
        score = 0.0

        if _canonical_url(url) == original:
            row.update(_relevance_fields("unrelated", 0.0, [], "original_url_excluded", False))
            assessed.append(row)
            continue

        overlap = len(target_terms.intersection(result_terms)) / max(len(target_terms), 1)
        if target_title and len(target_terms) >= 2 and target_title in combined:
            score += 0.45
            matched.append("exact_title_phrase")
        if overlap >= 0.6:
            score += 0.45
            matched.append("title_term_overlap")
        elif overlap >= 0.3:
            score += 0.2
            matched.append("partial_title_overlap")
        if target_domain and result_domain == target_domain:
            score += 0.2
            matched.append("source_domain_match")
        if source_signal and source_signal in combined:
            score += 0.15
            matched.append("organization_match")

        score = round(min(score, 1.0), 2)
        if score >= 0.65:
            status, reason = "relevant", None
        elif score >= 0.45:
            status, reason = "ambiguous", "requires_multiple_independent_moderate_results"
        elif score >= 0.2:
            status, reason = "weak", "insufficient_target_overlap"
        else:
            status, reason = "unrelated", "no_meaningful_target_match"
        row.update(_relevance_fields(status, score, matched, reason, False))
        assessed.append(row)

    accepted_indexes: set[int] = {
        index for index, row in enumerate(assessed) if row["relevance_status"] == "relevant"
    }
    if not accepted_indexes:
        moderate_by_domain: dict[str, int] = {}
        for index, row in enumerate(assessed):
            if row["relevance_status"] != "ambiguous":
                continue
            domain = _domain(str(row.get("url") or ""))
            if domain and domain not in moderate_by_domain:
                moderate_by_domain[domain] = index
        if len(moderate_by_domain) >= 2:
            accepted_indexes.update(moderate_by_domain.values())

    seen_domains: set[str] = set()
    for index in sorted(accepted_indexes):
        domain = _domain(str(assessed[index].get("url") or ""))
        if domain in seen_domains:
            assessed[index]["rejection_reason"] = "duplicate_source_domain"
            continue
        seen_domains.add(domain)
        assessed[index]["accepted_for_evidence"] = True
        assessed[index]["rejection_reason"] = None
    return assessed


def relevant_enrichment_findings(findings: list[dict]) -> list[dict]:
    return [row for row in findings if row.get("accepted_for_evidence") is True]


def build_evidence_bundle(
    item: ContentItem,
    extraction: ArticleExtractionResult | None = None,
    enrichment: WebEnrichmentResult | None = None,
) -> list[dict]:
    evidence: list[dict] = []
    if item.title:
        evidence.append(
            _evidence(
                "rss:title",
                "original_title",
                item.title,
                item.canonical_url,
                _source_name(item),
                item.published_at,
            )
        )
    excerpt = item.summary or item.content_text
    if excerpt:
        evidence.append(
            _evidence(
                "rss:excerpt",
                "original_excerpt",
                excerpt[:MAX_EXCERPT_TEXT],
                item.canonical_url,
                _source_name(item),
                item.published_at,
            )
        )
    if extraction and extraction.status == "ok" and extraction.content_text:
        evidence.append(
            _evidence(
                f"extraction:{extraction.id}",
                "extracted_article",
                extraction.content_text[:MAX_PRIMARY_TEXT],
                extraction.final_url or extraction.source_url,
                _domain(extraction.final_url or extraction.source_url),
                extraction.published_at,
            )
        )
    if enrichment and enrichment.status == "ok":
        for index, finding in enumerate(relevant_enrichment_findings(enrichment.findings_json)):
            text = " ".join(
                value for value in (str(finding.get("title") or ""), str(finding.get("snippet") or "")) if value
            )
            evidence.append(
                _evidence(
                    f"enrichment:{enrichment.id}:{index}",
                    "enrichment",
                    text[:MAX_ENRICHMENT_TEXT],
                    str(finding.get("url") or ""),
                    finding.get("source_name"),
                    finding.get("published_at"),
                    accepted=True,
                )
            )
    return evidence[:12]


def _relevance_fields(status, score, matched, reason, accepted) -> dict:
    return {
        "relevance_status": status,
        "relevance_score": score,
        "matched_signals": matched,
        "rejection_reason": reason,
        "accepted_for_evidence": accepted,
    }


def _evidence(evidence_id, kind, text, source_url, source_name, published_at, *, accepted=True) -> dict:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "text": " ".join(str(text).split()),
        "source_url": source_url,
        "source_name": source_name,
        "published_at": published_at.isoformat() if hasattr(published_at, "isoformat") else published_at,
        "accepted": accepted,
    }


def _terms(value: str) -> set[str]:
    return {term for term in TOKEN_RE.findall(value.casefold()) if len(term) >= 3}


def _normalize(value: str) -> str:
    return " ".join(TOKEN_RE.findall(value.casefold()))


def _domain(value: str | None) -> str | None:
    if not value:
        return None
    return (urlsplit(value).hostname or "").removeprefix("www.").casefold() or None


def _canonical_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.hostname:
        return None
    return f"{parsed.scheme.casefold()}://{parsed.hostname.casefold()}{parsed.path.rstrip('/') or '/'}"


def _source_name(item: ContentItem) -> str | None:
    return (item.classification_metadata or {}).get("source_name") or _domain(item.canonical_url)
