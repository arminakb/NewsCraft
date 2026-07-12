from __future__ import annotations

import re
import uuid

from pydantic import ValidationError

from app.content_production.evidence import build_evidence_bundle, relevant_enrichment_findings
from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.llm import (
    BriefGenerationOutput,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    output_schema,
    prompt_hash,
    response_metadata,
    schema_validation_diagnostics,
)
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import (
    ArticleExtractionResult,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    EditorialBrief,
    WebEnrichmentResult,
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!؟?])\s+")
UNSAFE_TERMS = ("rumor", "unconfirmed", "reportedly", "allegedly", "شایعه", "تایید نشده")


class EditorialBriefService:
    def __init__(self, session, *, provider: LLMProvider | None = None, timeout_seconds=45.0, max_output_tokens=1800):
        self.session = session
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    async def create_brief(
        self,
        *,
        run: ContentProductionRun,
        item: ContentItem,
        request: ContentProductionRequest | None = None,
        extraction: ArticleExtractionResult | None = None,
        enrichment: WebEnrichmentResult | None = None,
        command_id: uuid.UUID | None = None,
    ) -> EditorialBrief:
        brief_id = artifact_id(command_id or run.id, "editorial_brief")

        async def create() -> EditorialBrief:
            repository = ContentProductionRepository(self.session)
            if run.state == WorkflowState.SUFFICIENCY_SUFFICIENT.value:
                await repository.transition_run(run, WorkflowState.BRIEFING, current_step="editorial_brief")

            evidence = build_evidence_bundle(item, extraction, enrichment)
            if self.provider is None:
                payload = build_editorial_brief_payload(
                    item=item,
                    request=request,
                    extraction=extraction,
                    enrichment=enrichment,
                )
                metadata = {}
            else:
                payload, metadata = await self._generate_brief(evidence, request)
            brief = EditorialBrief(
                id=brief_id,
                production_run_id=run.id,
                angle=payload["angle"],
                key_facts_json=payload["key_facts"],
                source_claims_json=payload["source_claims"],
                unsafe_or_unverified_claims_json=payload["unsafe_or_unverified_claims"],
                audience=payload["audience"],
                tone=payload["tone"],
                do_not_say_json=payload["do_not_say"],
                evidence_ids_json=[row["evidence_id"] for row in evidence],
                generation_metadata_json=metadata,
            )
            self.session.add(brief)
            await self.session.flush()
            await repository.transition_run(run, WorkflowState.BRIEF_READY, current_step="editorial_brief")
            return brief

        return await create_or_get_artifact(self.session, EditorialBrief, brief_id, create)

    async def _generate_brief(
        self,
        evidence: list[dict],
        request: ContentProductionRequest | None,
    ) -> tuple[dict, dict]:
        if not evidence:
            raise LLMProviderError("insufficient_evidence", retryable=False)
        instructions = (
            "Create one Persian editorial brief using only the supplied evidence. Return the strict JSON schema. "
            "Every factual claim and source context must cite evidence_ids. State uncertainty; never invent context. "
            f"Audience: {request.audience if request else 'Persian Telegram readers'}. "
            f"Tone: {request.tone if request else 'professional and clear'}."
        )
        response = await self.provider.generate(
            LLMRequest(
                operation="editorial_brief",
                instructions=instructions,
                evidence=evidence,
                output_schema=output_schema(BriefGenerationOutput),
                timeout_seconds=self.timeout_seconds,
                max_output_tokens=self.max_output_tokens,
            )
        )
        try:
            output = BriefGenerationOutput.model_validate(response.output).validate_evidence_ids(
                {row["evidence_id"] for row in evidence}
            )
        except (ValidationError, ValueError) as exc:
            raise LLMProviderError(
                "schema_validation_failed",
                retryable=False,
                diagnostics=schema_validation_diagnostics(exc),
            ) from exc
        evidence_by_id = {row["evidence_id"]: row for row in evidence}
        key_facts = []
        for fact in output.key_facts:
            source = evidence_by_id[fact.evidence_ids[0]]
            key_facts.append(
                {
                    "claim": fact.claim,
                    "evidence_ids": fact.evidence_ids,
                    "source_url": source.get("source_url"),
                    "confidence": "llm_grounded",
                }
            )
        source_claims = [
            {
                "claim": row["text"],
                "evidence_id": row["evidence_id"],
                "source": row["kind"],
                "source_url": row.get("source_url"),
                "source_name": row.get("source_name"),
            }
            for row in evidence
        ]
        metadata = response_metadata(
            response,
            "editorial_brief",
            prompt_hash(instructions, evidence),
            [row["evidence_id"] for row in evidence],
        )
        return (
            {
                "angle": output.persian_angle,
                "key_facts": key_facts,
                "source_claims": source_claims,
                "unsafe_or_unverified_claims": [
                    {"claim": value, "reason": "llm_identified_uncertainty"} for value in output.uncertainties
                ],
                "audience": request.audience if request else None,
                "tone": request.tone if request else None,
                "do_not_say": output.prohibited_claims,
            },
            metadata,
        )


def build_editorial_brief_payload(
    *,
    item: ContentItem,
    request: ContentProductionRequest | None = None,
    extraction: ArticleExtractionResult | None = None,
    enrichment: WebEnrichmentResult | None = None,
) -> dict:
    primary_text = _best_primary_text(item, extraction)
    source_url = extraction.final_url if extraction and extraction.final_url else item.canonical_url
    key_facts = _confirmed_facts(primary_text, source_url, item.title)
    source_claims = _source_claims(item, extraction)
    unsafe_claims = _unsafe_claims(primary_text, enrichment)
    unconfirmed_context = _unconfirmed_context(enrichment)
    unsafe_claims.extend(unconfirmed_context)
    do_not_say = _do_not_say(unsafe_claims, extraction, enrichment)

    return {
        "angle": _angle(item, request),
        "key_facts": key_facts,
        "source_claims": source_claims,
        "unsafe_or_unverified_claims": unsafe_claims,
        "audience": request.audience if request else None,
        "tone": request.tone if request else None,
        "do_not_say": do_not_say,
    }


def _best_primary_text(item: ContentItem, extraction: ArticleExtractionResult | None) -> str:
    if extraction and extraction.status == "ok" and extraction.content_text:
        return extraction.content_text
    return item.content_text or item.summary or item.title or ""


def _confirmed_facts(text: str, source_url: str | None, fallback_title: str | None) -> list[dict]:
    facts: list[dict] = []
    if fallback_title:
        facts.append({"claim": fallback_title, "source_url": source_url, "confidence": "source_title"})
    for sentence in _sentences(text)[:5]:
        if _has_unsafe_term(sentence):
            continue
        facts.append({"claim": sentence, "source_url": source_url, "confidence": "confirmed_primary"})
    return facts[:6]


def _source_claims(item: ContentItem, extraction: ArticleExtractionResult | None) -> list[dict]:
    claims = []
    if item.summary:
        claims.append({"claim": item.summary, "source": "content_item_summary", "source_url": item.canonical_url})
    if extraction and extraction.summary:
        claims.append(
            {
                "claim": extraction.summary,
                "source": "article_extraction_summary",
                "source_url": extraction.final_url,
            }
        )
    return claims


def _unsafe_claims(text: str, enrichment: WebEnrichmentResult | None) -> list[dict]:
    claims = [
        {"claim": sentence, "reason": "unsafe_or_unverified_language"}
        for sentence in _sentences(text)
        if _has_unsafe_term(sentence)
    ]
    if enrichment and enrichment.status not in {"ok", "skipped"}:
        claims.append({"claim": "web enrichment failed", "reason": enrichment.error_message or enrichment.status})
    return claims


def _unconfirmed_context(enrichment: WebEnrichmentResult | None) -> list[dict]:
    if not enrichment or enrichment.status != "ok":
        return []
    return [
        {
            "claim": finding.get("snippet") or finding.get("title"),
            "source_url": finding.get("url"),
            "reason": "secondary_web_enrichment_not_primary_truth",
        }
        for finding in relevant_enrichment_findings(enrichment.findings_json)
        if finding.get("snippet") or finding.get("title")
    ]


def _do_not_say(
    unsafe_claims: list[dict],
    extraction: ArticleExtractionResult | None,
    enrichment: WebEnrichmentResult | None,
) -> list[str]:
    values = ["Do not add facts that are absent from primary evidence."]
    if unsafe_claims:
        values.append("Do not present unverified or secondary claims as confirmed.")
    if extraction and extraction.status != "ok":
        values.append("Do not rely on failed or fallback extraction as full article evidence.")
    if enrichment and enrichment.status == "skipped":
        values.append("Do not imply independent web confirmation was performed.")
    return values


def _angle(item: ContentItem, request: ContentProductionRequest | None) -> str:
    topic = request.topic if request and request.topic else item.content_intent or item.content_type or "news"
    title = item.title or "the selected story"
    return f"Explain why {title} matters for {topic} readers."


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text.replace("\n", " ")) if len(part.strip()) >= 24]


def _has_unsafe_term(text: str) -> bool:
    normalized = text.casefold()
    return any(term in normalized for term in UNSAFE_TERMS)
