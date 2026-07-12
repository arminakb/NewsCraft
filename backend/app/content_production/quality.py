from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal

from pydantic import ValidationError

from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.llm import (
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    QualityEvaluationOutput,
    output_schema,
    prompt_hash,
    quality_gate_status,
    response_metadata,
    schema_validation_diagnostics,
)
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import ContentProductionRun, DraftQualityReport, EditorialBrief, TelegramDraft

HYPE_TERMS = ("انقلابی", "بی نظیر", "قطعا", "همیشه", "هرگز", "guaranteed", "revolutionary")


class DraftQualityService:
    def __init__(self, session, *, provider: LLMProvider | None = None, timeout_seconds=45.0, max_output_tokens=1800):
        self.session = session
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    async def check_draft(
        self,
        *,
        run: ContentProductionRun,
        draft: TelegramDraft,
        brief: EditorialBrief,
        command_id: uuid.UUID | None = None,
    ) -> DraftQualityReport:
        report_id = artifact_id(command_id or run.id, "draft_quality_report", str(draft.id))

        async def create() -> DraftQualityReport:
            repository = ContentProductionRepository(self.session)
            if run.state == WorkflowState.DRAFT_READY.value:
                await repository.transition_run(run, WorkflowState.QUALITY_CHECKING, current_step="draft_quality")

            if self.provider is None:
                payload = evaluate_draft_quality(draft, brief)
                rubric = {}
                metadata = {}
            else:
                payload, rubric, metadata = await self._evaluate_with_provider(draft, brief)
            report = DraftQualityReport(
                id=report_id,
                production_run_id=run.id,
                draft_id=draft.id,
                status=payload["status"],
                score=payload["score"],
                factuality_warnings_json=payload["factuality_warnings"],
                unsupported_claims_json=payload["unsupported_claims"],
                style_warnings_json=payload["style_warnings"],
                required_revisions_json=payload["required_revisions"],
                rubric_json=rubric,
                evaluation_metadata_json=metadata,
            )
            self.session.add(report)
            await self.session.flush()
            target_state = {
                "passed": WorkflowState.QUALITY_PASSED,
                "failed": WorkflowState.QUALITY_FAILED,
                "revision_requested": WorkflowState.REVISION_REQUESTED,
            }[report.status]
            await repository.transition_run(run, target_state, current_step="draft_quality")
            return report

        return await create_or_get_artifact(self.session, DraftQualityReport, report_id, create)

    async def _evaluate_with_provider(self, draft: TelegramDraft, brief: EditorialBrief) -> tuple[dict, dict, dict]:
        evidence = [
            {
                "evidence_id": row.get("evidence_id"),
                "kind": row.get("source"),
                "text": str(row.get("claim") or "")[:6000],
                "source_url": row.get("source_url"),
            }
            for row in brief.source_claims_json or []
            if row.get("evidence_id") and row.get("claim")
        ]
        if not evidence:
            raise LLMProviderError("insufficient_evidence", retryable=False)
        brief_context = json.dumps(
            {"angle": brief.angle, "key_facts": brief.key_facts_json},
            ensure_ascii=False,
        )[:5000]
        instructions = (
            "Evaluate the exact Persian Telegram draft only against the supplied brief and evidence. "
            "Score every rubric field from 1 to 5. Flag unsupported claims, poor Persian, irrelevant content, "
            "misleading certainty, attribution gaps and instruction leakage. Do not infer hidden reasoning. "
            f"Brief: {brief_context} "
            f"Draft: {draft.draft_text[:4096]}"
        )
        response = await self.provider.generate(
            LLMRequest(
                operation="draft_quality_evaluation",
                instructions=instructions,
                evidence=evidence,
                output_schema=output_schema(QualityEvaluationOutput),
                timeout_seconds=self.timeout_seconds,
                max_output_tokens=self.max_output_tokens,
            )
        )
        try:
            output = QualityEvaluationOutput.model_validate(response.output)
        except ValidationError as exc:
            raise LLMProviderError(
                "schema_validation_failed",
                retryable=False,
                diagnostics=schema_validation_diagnostics(exc),
            ) from exc
        status = quality_gate_status(output)
        scores = [
            output.factual_fidelity,
            output.evidence_coverage,
            output.persian_readability,
            output.naturalness,
            output.concision,
            output.structure,
            output.headline_quality,
            output.source_attribution,
            output.unsupported_claim_risk,
            output.publication_readiness,
        ]
        metadata = response_metadata(
            response,
            "draft_quality_evaluation",
            prompt_hash(instructions, evidence),
            list(draft.evidence_ids_json or []),
        )
        metadata["quality_decision"] = output.recommendation
        return (
            {
                "status": status,
                "score": Decimal(sum(scores)) / Decimal("50"),
                "factuality_warnings": list(output.unsupported_claims),
                "unsupported_claims": list(output.unsupported_claims),
                "style_warnings": [
                    *output.awkward_persian_phrases,
                    *output.irrelevant_content,
                    *output.internal_instruction_leakage,
                ],
                "required_revisions": [
                    *output.missing_essential_facts,
                    *output.misleading_certainty,
                ],
            },
            output.model_dump(mode="json"),
            metadata,
        )


def evaluate_draft_quality(draft: TelegramDraft, brief: EditorialBrief) -> dict:
    factuality_warnings: list[str] = []
    unsupported_claims = _unsupported_claims(draft, brief)
    style_warnings = _style_warnings(draft, brief)
    required_revisions: list[str] = []

    if unsupported_claims:
        factuality_warnings.append("draft_contains_claims_not_found_in_brief")
        required_revisions.append("remove_or_source_unsupported_claims")
    if not draft.source_links_json:
        factuality_warnings.append("missing_source_link")
        required_revisions.append("add_source_link")
    if style_warnings:
        required_revisions.append("fix_telegram_structure_or_tone")

    score = Decimal("1.0")
    score -= Decimal("0.35") if unsupported_claims else Decimal("0")
    score -= Decimal("0.25") if not draft.source_links_json else Decimal("0")
    score -= Decimal("0.15") if style_warnings else Decimal("0")
    score = max(score, Decimal("0"))

    if unsupported_claims or not draft.source_links_json:
        status = "failed"
    elif style_warnings:
        status = "revision_requested"
    else:
        status = "passed"
    return {
        "status": status,
        "score": score,
        "factuality_warnings": factuality_warnings,
        "unsupported_claims": unsupported_claims,
        "style_warnings": style_warnings,
        "required_revisions": list(dict.fromkeys(required_revisions)),
    }


def _unsupported_claims(draft: TelegramDraft, brief: EditorialBrief) -> list[str]:
    allowed_text = " ".join(
        str(value.get("claim", ""))
        for value in [*(brief.key_facts_json or []), *(brief.source_claims_json or [])]
    )
    normalized_allowed = _normalize_claim_text(allowed_text)
    unsupported = []
    for line in draft.draft_text.splitlines():
        stripped = line.strip().removeprefix("-").strip()
        if not stripped or stripped.startswith(("تیتر:", "زاویه خبر:", "نکات اصلی", "منبع:", "هشدار", "#")):
            continue
        if stripped.startswith("http") or stripped in (draft.source_links_json or []):
            continue
        normalized = _normalize_claim_text(stripped)
        if normalized not in normalized_allowed and not any(
            stripped in str(warning) for warning in draft.warnings_json or []
        ):
            unsupported.append(stripped)
    return unsupported


def _style_warnings(draft: TelegramDraft, brief: EditorialBrief) -> list[str]:
    warnings = []
    text = draft.draft_text
    if "تیتر:" not in text or "نکات اصلی:" not in text:
        warnings.append("missing_telegram_structure")
    if len(text) < 80:
        warnings.append("too_little_context")
    if _has_hype(text):
        warnings.append("too_much_hype")
    if brief.tone and brief.tone.casefold() in {"clear", "neutral", "restrained"} and _has_hype(text):
        warnings.append("tone_mismatch")
    return list(dict.fromkeys(warnings))


def _has_hype(text: str) -> bool:
    return bool(re.search(r"!{2,}", text)) or any(term in text.casefold() for term in HYPE_TERMS)


def _normalize_claim_text(value: str) -> str:
    return re.sub(r"[^\w\u0600-\u06ff]+", " ", value.casefold()).strip()
