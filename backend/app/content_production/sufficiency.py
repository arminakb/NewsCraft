from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from app.content_production.evidence import relevant_enrichment_findings
from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import (
    ArticleExtractionResult,
    ContentItem,
    ContentProductionRun,
    ContentSufficiencyReport,
    WebEnrichmentResult,
)

MEANINGFUL_RE = re.compile(r"[\w\u0600-\u06ff]", re.UNICODE)
PROMOTIONAL_TERMS = ("discount", "coupon", "buy now", "sale", "promo", "تخفیف", "خرید")


@dataclass(frozen=True)
class SufficiencyDecision:
    status: str
    score: Decimal
    reasons: list[str]
    allowed_next_step: str | None
    blocked_steps: list[str]
    minimum_needed: list[str]
    input_snapshot: dict


class SufficiencyStage(StrEnum):
    ORIGINAL = "original"
    POST_EXTRACTION = "post_extraction"
    POST_ENRICHMENT = "post_enrichment"


@dataclass(frozen=True)
class SufficiencyInputs:
    stage: SufficiencyStage
    run: ContentProductionRun
    item: ContentItem
    source_event_id: uuid.UUID
    extraction: ArticleExtractionResult | None = None
    enrichment: WebEnrichmentResult | None = None

    @property
    def supplemental_text(self) -> str:
        values: list[str] = []
        if self.extraction and self.extraction.status in {"ok", "fallback"}:
            values.extend(
                [self.extraction.title or "", self.extraction.summary or "", self.extraction.content_text or ""]
            )
        if self.enrichment and self.enrichment.status == "ok":
            for finding in relevant_enrichment_findings(self.enrichment.findings_json):
                if isinstance(finding, dict):
                    values.extend(str(finding.get(key) or "") for key in ("title", "snippet"))
        return "\n".join(value for value in values if value)


class SufficiencyInputAssembler:
    def __init__(self, session):
        self.session = session

    async def assemble(
        self,
        *,
        run: ContentProductionRun,
        item: ContentItem,
        stage: SufficiencyStage,
        source_event_id: uuid.UUID,
        extraction_result_id: uuid.UUID | None = None,
        enrichment_result_id: uuid.UUID | None = None,
    ) -> SufficiencyInputs:
        if stage == SufficiencyStage.ORIGINAL and (extraction_result_id or enrichment_result_id):
            raise ValueError("original sufficiency stage cannot reference derived artifacts")
        if stage == SufficiencyStage.POST_EXTRACTION and extraction_result_id is None:
            raise ValueError("post_extraction sufficiency requires extraction_result_id")
        if stage == SufficiencyStage.POST_EXTRACTION and enrichment_result_id is not None:
            raise ValueError("post_extraction sufficiency cannot reference enrichment")
        if stage == SufficiencyStage.POST_ENRICHMENT and enrichment_result_id is None:
            raise ValueError("post_enrichment sufficiency requires enrichment_result_id")

        extraction = await self._artifact(ArticleExtractionResult, extraction_result_id, run, item)
        enrichment = await self._artifact(WebEnrichmentResult, enrichment_result_id, run, item)
        return SufficiencyInputs(
            stage=stage,
            run=run,
            item=item,
            source_event_id=source_event_id,
            extraction=extraction,
            enrichment=enrichment,
        )

    async def _artifact(self, model, object_id, run, item):
        if object_id is None:
            return None
        artifact = await self.session.get(model, object_id)
        if artifact is None:
            raise LookupError(f"{model.__name__} not found: {object_id}")
        if artifact.production_run_id != run.id or artifact.content_item_id != item.id:
            raise ValueError(f"{model.__name__} does not belong to the sufficiency routing chain")
        return artifact


class ContentSufficiencyService:
    def __init__(self, session):
        self.session = session

    async def check_run(
        self,
        run: ContentProductionRun,
        item: ContentItem,
        *,
        inputs: SufficiencyInputs | None = None,
        command_id: uuid.UUID | None = None,
    ) -> ContentSufficiencyReport:
        report_id = artifact_id(command_id or run.id, "content_sufficiency_report")

        async def create() -> ContentSufficiencyReport:
            repository = ContentProductionRepository(self.session)
            if run.state in {
                WorkflowState.SHORTLIST_APPROVED.value,
                WorkflowState.ARTICLE_EXTRACTED.value,
                WorkflowState.ENRICHED.value,
            }:
                await repository.transition_run(
                    run,
                    WorkflowState.SUFFICIENCY_CHECKING,
                    current_step="content_sufficiency",
                )

            inputs_value = inputs or SufficiencyInputs(
                stage=SufficiencyStage.ORIGINAL,
                run=run,
                item=item,
                source_event_id=command_id or run.id,
            )
            try:
                decision = evaluate_content_sufficiency(item, supplemental_text=inputs_value.supplemental_text)
            except Exception as exc:
                decision = SufficiencyDecision(
                    status="evaluation_failed",
                    score=Decimal("0"),
                    reasons=[f"evaluator_failure:{type(exc).__name__}"],
                    allowed_next_step=None,
                    blocked_steps=["draft_generation", "telegram_package"],
                    minimum_needed=["successful_sufficiency_evaluation"],
                    input_snapshot={},
                )
            decision = replace(
                decision,
                input_snapshot={
                    **decision.input_snapshot,
                    "stage": inputs_value.stage.value,
                    "source_event_id": str(inputs_value.source_event_id),
                    "extraction_result_id": str(inputs_value.extraction.id) if inputs_value.extraction else None,
                    "enrichment_result_id": str(inputs_value.enrichment.id) if inputs_value.enrichment else None,
                    "enrichment_provider": inputs_value.enrichment.provider_name if inputs_value.enrichment else None,
                },
            )
            report = ContentSufficiencyReport(
                id=report_id,
                production_run_id=run.id,
                content_item_id=item.id,
                status=decision.status,
                score=decision.score,
                reasons_json=decision.reasons,
                allowed_next_step=decision.allowed_next_step,
                blocked_steps_json=decision.blocked_steps,
                minimum_needed_json=decision.minimum_needed,
                input_snapshot_json=decision.input_snapshot,
            )
            self.session.add(report)
            await self.session.flush()

            target_state = {
                "sufficient": WorkflowState.SUFFICIENCY_SUFFICIENT,
                "partial": WorkflowState.SUFFICIENCY_PARTIAL,
                "insufficient": WorkflowState.SUFFICIENCY_INSUFFICIENT,
                "rejected": WorkflowState.FAILED,
                "evaluation_failed": WorkflowState.FAILED,
            }[decision.status]
            await repository.transition_run(
                run,
                target_state,
                current_step="content_sufficiency",
                failure_reason=(
                    "content rejected by sufficiency gate"
                    if decision.status == "rejected"
                    else "sufficiency evaluation failed"
                    if decision.status == "evaluation_failed"
                    else None
                ),
            )
            return report

        return await create_or_get_artifact(self.session, ContentSufficiencyReport, report_id, create)


def evaluate_content_sufficiency(item: ContentItem, *, supplemental_text: str = "") -> SufficiencyDecision:
    title = (item.title or "").strip()
    source_url = (item.canonical_url or "").strip()
    summary = (item.summary or "").strip()
    content_text = (item.content_text or "").strip()
    html_text = _htmlish_text(item.content_html_sanitized or "")
    combined_text = "\n".join(value for value in (content_text, html_text, summary, supplemental_text) if value)
    meaningful_chars = len(MEANINGFUL_RE.findall(combined_text))
    has_title = bool(title)
    has_source = bool(source_url)
    has_media = bool(item.primary_image_id)
    reasons: list[str] = []
    minimum_needed: list[str] = []
    score = Decimal("0")

    if has_title:
        score += Decimal("0.12")
    else:
        reasons.append("missing_title")
        minimum_needed.append("title")

    if has_source:
        score += Decimal("0.14")
    else:
        reasons.append("missing_source_url")
        minimum_needed.append("source_confirmation")

    if item.duplicate_of_id:
        return _decision(
            "rejected",
            Decimal("0.05"),
            [*reasons, "duplicate_content"],
            None,
            ["draft_generation", "telegram_package"],
            [*minimum_needed, "unique_source_item"],
            item,
            meaningful_chars,
            has_media,
        )

    if item.content_type in {"promo", "low_signal"} or _contains_promotional_terms(title, summary, content_text):
        return _decision(
            "rejected",
            Decimal("0.12"),
            [*reasons, "promotional_or_low_signal"],
            None,
            ["draft_generation", "telegram_package"],
            [*minimum_needed, "reliable_non_promotional_source"],
            item,
            meaningful_chars,
            has_media,
        )

    if item.freshness_bucket in {"stale", "archive"} and item.content_type != "longform":
        reasons.append("stale_or_archive")
        minimum_needed.append("human_freshness_review")
        score -= Decimal("0.10")

    if meaningful_chars >= 1400:
        score += Decimal("0.62")
        reasons.append("full_article_like_content")
    elif meaningful_chars >= 500:
        score += Decimal("0.42")
        reasons.append("partial_article_content")
        minimum_needed.extend(["supporting_facts", "source_confirmation"])
    elif meaningful_chars >= 120:
        score += Decimal("0.24")
        reasons.append("short_rss_or_telegram_text")
        minimum_needed.extend(["full_article_text", "supporting_facts"])
    elif summary:
        score += Decimal("0.14")
        reasons.append("rss_summary_only")
        minimum_needed.extend(["full_article_text", "supporting_facts", "source_confirmation"])
    else:
        reasons.append("title_only_or_empty_body")
        minimum_needed.extend(["full_article_text", "supporting_facts", "source_confirmation"])

    if item.item_type == "telegram" and meaningful_chars >= 280 and has_source:
        score += Decimal("0.12")
        reasons.append("telegram_text_has_context")

    if item.is_rewrite_ready:
        score += Decimal("0.10")
        reasons.append("rewrite_ready")
    elif item.rewrite_blockers:
        reasons.extend(f"rewrite_blocker:{blocker}" for blocker in item.rewrite_blockers[:5])

    normalized_score = max(Decimal("0"), min(score, Decimal("1")))
    if normalized_score >= Decimal("0.72") and has_title and has_source:
        return _decision(
            "sufficient",
            normalized_score,
            reasons,
            "editorial_brief",
            [],
            [],
            item,
            meaningful_chars,
            has_media,
        )
    if normalized_score >= Decimal("0.38") and has_title:
        return _decision(
            "partial",
            normalized_score,
            reasons,
            "article_extraction" if has_source else "web_enrichment",
            ["draft_generation", "telegram_package"],
            _dedupe(minimum_needed or ["full_article_text", "supporting_facts"]),
            item,
            meaningful_chars,
            has_media,
        )
    return _decision(
        "insufficient",
        normalized_score,
        reasons,
        "article_extraction" if has_source else "human_review",
        ["draft_generation", "telegram_package"],
        _dedupe(minimum_needed or ["full_article_text", "supporting_facts", "source_confirmation"]),
        item,
        meaningful_chars,
        has_media,
    )


def _decision(
    status: str,
    score: Decimal,
    reasons: list[str],
    allowed_next_step: str | None,
    blocked_steps: list[str],
    minimum_needed: list[str],
    item: ContentItem,
    meaningful_chars: int,
    has_media: bool,
) -> SufficiencyDecision:
    return SufficiencyDecision(
        status=status,
        score=score,
        reasons=_dedupe(reasons),
        allowed_next_step=allowed_next_step,
        blocked_steps=blocked_steps,
        minimum_needed=_dedupe(minimum_needed),
        input_snapshot={
            "content_item_id": str(item.id),
            "title": item.title,
            "source_url": item.canonical_url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "content_type": item.content_type,
            "freshness_bucket": item.freshness_bucket,
            "is_rewrite_ready": item.is_rewrite_ready,
            "meaningful_chars": meaningful_chars,
            "has_media": has_media,
        },
    )


def _htmlish_text(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _contains_promotional_terms(*values: str) -> bool:
    text = " ".join(values).casefold()
    return any(term in text for term in PROMOTIONAL_TERMS)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
