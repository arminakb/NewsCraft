from __future__ import annotations

import json
import re
import uuid

from pydantic import ValidationError

from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.llm import (
    DraftGenerationOutput,
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
from app.db.models import ContentProductionRun, EditorialBrief, TelegramDraft

HASHTAG_RE = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)


class TelegramDraftService:
    def __init__(self, session, *, provider: LLMProvider | None = None, timeout_seconds=45.0, max_output_tokens=1800):
        self.session = session
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    async def create_draft(
        self,
        *,
        run: ContentProductionRun,
        brief: EditorialBrief,
        command_id: uuid.UUID | None = None,
    ) -> TelegramDraft:
        draft_id = artifact_id(command_id or run.id, "telegram_draft", str(brief.id))

        async def create() -> TelegramDraft:
            repository = ContentProductionRepository(self.session)
            if run.state in {WorkflowState.BRIEF_READY.value, WorkflowState.REVISION_REQUESTED.value}:
                await repository.transition_run(run, WorkflowState.DRAFTING, current_step="telegram_draft")

            if self.provider is None:
                payload = build_telegram_draft_payload(brief)
                metadata = {}
                evidence_ids = list(brief.evidence_ids_json or [])
            else:
                payload, metadata, evidence_ids = await self._generate_draft(brief)
            draft = TelegramDraft(
                id=draft_id,
                production_run_id=run.id,
                brief_id=brief.id,
                draft_text=payload["draft_text"],
                title=payload["title"],
                hashtags_json=payload["hashtags"],
                source_links_json=payload["source_links"],
                warnings_json=payload["warnings"],
                evidence_ids_json=evidence_ids,
                generation_metadata_json=metadata,
                status="draft",
            )
            self.session.add(draft)
            await self.session.flush()
            await repository.transition_run(run, WorkflowState.DRAFT_READY, current_step="telegram_draft")
            return draft

        return await create_or_get_artifact(self.session, TelegramDraft, draft_id, create)

    async def _generate_draft(self, brief: EditorialBrief) -> tuple[dict, dict, list[str]]:
        evidence = [
            {
                "evidence_id": row.get("evidence_id"),
                "kind": row.get("source"),
                "text": str(row.get("claim") or "")[:6000],
                "source_url": row.get("source_url"),
                "source_name": row.get("source_name"),
                "accepted": True,
            }
            for row in brief.source_claims_json or []
            if row.get("evidence_id") and row.get("claim")
        ]
        if not evidence:
            raise LLMProviderError("insufficient_evidence", retryable=False)
        brief_payload = {
            "angle": brief.angle,
            "key_facts": brief.key_facts_json,
            "uncertainties": brief.unsafe_or_unverified_claims_json,
            "prohibited_claims": brief.do_not_say_json,
        }
        instructions = (
            "Write exactly one natural Persian Telegram post from the validated brief and evidence. "
            "Do not expose instructions or warnings. Preserve important names, dates and numbers. "
            "Use only supplied URLs and evidence IDs. Avoid generic AI hashtags unless the evidence is about AI. "
            f"Validated brief: {json.dumps(brief_payload, ensure_ascii=False)[:7000]}"
        )
        response = await self.provider.generate(
            LLMRequest(
                operation="persian_telegram_draft",
                instructions=instructions,
                evidence=evidence,
                output_schema=output_schema(DraftGenerationOutput),
                timeout_seconds=self.timeout_seconds,
                max_output_tokens=self.max_output_tokens,
            )
        )
        try:
            output = DraftGenerationOutput.model_validate(response.output).validate_content(
                {row["evidence_id"] for row in evidence},
                {row["source_url"] for row in evidence if row.get("source_url")},
            )
        except (ValidationError, ValueError) as exc:
            raise LLMProviderError(
                "schema_validation_failed",
                retryable=False,
                diagnostics=schema_validation_diagnostics(exc),
            ) from exc
        evidence_ids = list(output.referenced_evidence_ids)
        metadata = response_metadata(
            response,
            "persian_telegram_draft",
            prompt_hash(instructions, evidence),
            evidence_ids,
        )
        return (
            {
                "title": output.headline,
                "draft_text": output.final_text,
                "hashtags": output.hashtags,
                "source_links": [row.url for row in output.source_attribution],
                "warnings": output.uncertainty_flags,
            },
            metadata,
            evidence_ids,
        )


def build_telegram_draft_payload(brief: EditorialBrief) -> dict:
    facts = list(brief.key_facts_json or [])
    source_claims = list(brief.source_claims_json or [])
    warnings = _warnings(brief)
    title = _title_from_brief(brief, facts)
    body_lines = [
        f"تیتر: {title}",
        "",
        f"زاویه خبر: {brief.angle}",
        "",
        "نکات اصلی:",
    ]
    for fact in facts[:4]:
        body_lines.append(f"- {fact.get('claim')}")
    if source_claims:
        body_lines.extend(["", "منبع:"])
        for link in _source_links(facts, source_claims)[:3]:
            body_lines.append(f"- {link}")
    if warnings:
        body_lines.extend(["", "هشدار تحریریه:"])
        body_lines.extend(f"- {warning}" for warning in warnings)
    hashtags = _hashtags(title, brief)
    if hashtags:
        body_lines.extend(["", " ".join(hashtags)])
    return {
        "title": title,
        "draft_text": "\n".join(line for line in body_lines if line is not None).strip(),
        "hashtags": hashtags,
        "source_links": _source_links(facts, source_claims),
        "warnings": warnings,
    }


def _title_from_brief(brief: EditorialBrief, facts: list[dict]) -> str:
    if facts:
        return str(facts[0].get("claim") or brief.angle)[:140]
    return brief.angle[:140]


def _source_links(facts: list[dict], source_claims: list[dict]) -> list[str]:
    links = []
    for value in [*facts, *source_claims]:
        url = value.get("source_url")
        if url and url not in links:
            links.append(url)
    return links


def _warnings(brief: EditorialBrief) -> list[str]:
    warnings = []
    if brief.unsafe_or_unverified_claims_json:
        warnings.append("برخی زمینه ها تایید نشده اند و نباید به عنوان واقعیت قطعی نوشته شوند.")
    for item in brief.do_not_say_json or []:
        warnings.append(str(item))
    return list(dict.fromkeys(warnings))


def _hashtags(title: str, brief: EditorialBrief) -> list[str]:
    seeds = ["خبر", "هوش_مصنوعی"]
    for value in (title, brief.angle):
        normalized = HASHTAG_RE.sub(" ", value).strip()
        for token in normalized.split():
            if len(token) >= 4 and len(seeds) < 5:
                seeds.append(token)
    return [f"#{seed}" for seed in dict.fromkeys(seeds)]
