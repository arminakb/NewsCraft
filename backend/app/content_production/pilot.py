from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.api.routes import (
    approve_content_production_package,
    approve_content_production_shortlist,
    create_content_production_request,
)
from app.api.schemas import ContentProductionRequestCreateIn, ShortlistDecisionIn
from app.content_production.handlers import build_core_event_dispatcher
from app.content_production.orchestration import WorkflowEventWorker
from app.content_production.providers import build_production_provider_options
from app.content_production.repository import ContentProductionRepository
from app.core.config import settings
from app.db.models import (
    AgentStepRun,
    ArticleExtractionResult,
    CandidateShortlist,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    ContentSufficiencyReport,
    DraftQualityReport,
    EditorialBrief,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
    WebEnrichmentResult,
    WorkflowEvent,
)
from app.db.session import async_session


async def start_pilot(args) -> dict:
    async with async_session() as session:
        result = await create_content_production_request(
            ContentProductionRequestCreateIn(
                topic=args.topic,
                language="fa",
                tone=args.tone,
                audience=args.audience,
                max_candidates=args.max_candidates,
                require_rewrite_ready=not args.allow_not_rewrite_ready,
                require_media=False,
                created_by="step-7-pilot",
                constraints_json={
                    "pilot": True,
                    "pilot_content_item_ids": args.content_item_id,
                },
            ),
            session,
        )
        return {
            "request_id": str(result.id),
            "status": result.status,
            "next": "process events, then explicitly approve one shortlist execution",
        }


async def process_events(args) -> dict:
    async with async_session() as session:
        options = build_production_provider_options(settings)
        dispatcher = build_core_event_dispatcher(session, **options)
        worker = WorkflowEventWorker(
            ContentProductionRepository(session),
            dispatcher,
            max_attempts=args.max_attempts,
        )
        processed = 0
        batches = 0
        while batches < args.max_batches:
            count = await worker.run_once(limit=args.limit)
            if count == 0:
                break
            processed += count
            batches += 1
        return {
            "processed_events": processed,
            "batches": batches,
            "enrichment_provider": settings.enrichment_provider,
            "telegram_publish_attempted": False,
        }


async def approve_shortlist(args) -> dict:
    async with async_session() as session:
        rows = await approve_content_production_shortlist(
            UUID(args.request_id),
            ShortlistDecisionIn(
                selection_execution_id=UUID(args.selection_execution_id),
                content_item_ids=[UUID(value) for value in args.content_item_id],
            ),
            session,
        )
        return {
            "approved_content_item_ids": [str(row.content_item_id) for row in rows],
            "next": "process events; final package approval remains a separate command",
        }


async def approve_package(args) -> dict:
    async with async_session() as session:
        package = await approve_content_production_package(UUID(args.package_id), session)
        return {
            "package_id": str(package.id),
            "approval_status": package.approval_status,
            "next": "process events once to create the dispatch handoff; publishing is disabled",
        }


async def write_report(args) -> dict:
    request_id = UUID(args.request_id)
    human_reviews = _load_human_reviews(args.human_reviews)
    async with async_session() as session:
        request = await session.get(ContentProductionRequest, request_id)
        if request is None:
            raise LookupError("content production request not found")
        runs = list(
            await session.scalars(
                select(ContentProductionRun)
                .where(ContentProductionRun.request_id == request_id)
                .order_by(ContentProductionRun.created_at)
            )
        )
        events = list(
            await session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.correlation_id == request_id)
                .order_by(WorkflowEvent.occurred_at)
            )
        )
        shortlist = list(
            await session.scalars(
                select(CandidateShortlist)
                .where(CandidateShortlist.request_id == request_id)
                .order_by(CandidateShortlist.selection_execution_id, CandidateShortlist.rank)
            )
        )
        bundles = [await _run_bundle(session, run, human_reviews.get(str(run.id))) for run in runs]
        payload = {
            "schema_version": "step-7-pilot-v1",
            "generated_at": datetime.now().astimezone().isoformat(),
            "live_provider_status": {
                "extraction": "http_trafilatura",
                "enrichment": settings.enrichment_provider,
                "llm": (
                    f"{settings.llm_provider}:{settings.llm_model}"
                    if settings.llm_provider != "none"
                    else "disabled_no_live_provider_requested"
                ),
                "estimated_llm_cost": "unavailable_no_configured_pricing",
                "telegram_publishing": "disabled",
            },
            "request": _request_snapshot(request),
            "shortlist": [_shortlist_snapshot(row) for row in shortlist],
            "event_summary": [_event_snapshot(event) for event in events],
            "items": bundles,
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return {"report_path": str(output.resolve()), "item_count": len(bundles)}


async def _run_bundle(session, run: ContentProductionRun, human_review: dict | None) -> dict:
    item = await session.get(ContentItem, run.content_item_id)
    artifacts = {}
    for name, model in (
        ("extractions", ArticleExtractionResult),
        ("enrichments", WebEnrichmentResult),
        ("sufficiency_reports", ContentSufficiencyReport),
        ("briefs", EditorialBrief),
        ("drafts", TelegramDraft),
        ("quality_reports", DraftQualityReport),
        ("media_decisions", VisualBrief),
        ("packages", TelegramPostPackage),
        ("dispatch_handoffs", TelegramDispatchRequest),
        ("traces", AgentStepRun),
    ):
        order_column = getattr(model, "created_at", None)
        if order_column is None:
            order_column = model.started_at
        rows = list(
            await session.scalars(
                select(model).where(model.production_run_id == run.id).order_by(order_column)
            )
        )
        artifacts[name] = rows
    return {
        "production_run": {
            "id": str(run.id),
            "state": run.state,
            "current_step": run.current_step,
            "failure_reason": run.failure_reason,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        },
        "source": {
            "content_item_id": str(item.id),
            "url": item.canonical_url,
            "rss_title": item.title,
            "rss_excerpt": _bounded(item.summary or item.content_text or "", 1200),
        },
        "extraction": [_extraction_snapshot(row) for row in artifacts["extractions"]],
        "enrichment": [_enrichment_snapshot(row) for row in artifacts["enrichments"]],
        "sufficiency": [_sufficiency_snapshot(row) for row in artifacts["sufficiency_reports"]],
        "editorial_briefs": [_brief_snapshot(row) for row in artifacts["briefs"]],
        "drafts": [_draft_snapshot(row) for row in artifacts["drafts"]],
        "automated_quality": [_quality_snapshot(row) for row in artifacts["quality_reports"]],
        "media_decisions": [_media_snapshot(row) for row in artifacts["media_decisions"]],
        "packages": [_package_snapshot(row) for row in artifacts["packages"]],
        "dispatch_handoffs": [_dispatch_snapshot(row) for row in artifacts["dispatch_handoffs"]],
        "trace_summary": [_trace_snapshot(row) for row in artifacts["traces"]],
        "claim_source_map": _claim_source_map(artifacts["briefs"]),
        "human_review": human_review or {"status": "pending"},
        "automated_human_disagreement": _review_disagreement(artifacts["quality_reports"], human_review),
    }


def _request_snapshot(row) -> dict:
    return {
        "id": str(row.id),
        "topic": row.topic,
        "language": row.language,
        "tone": row.tone,
        "audience": row.audience,
        "status": row.status,
        "created_at": row.created_at,
    }


def _shortlist_snapshot(row) -> dict:
    return {
        "selection_execution_id": str(row.selection_execution_id),
        "content_item_id": str(row.content_item_id),
        "rank": row.rank,
        "score": row.score,
        "approval_status": row.approval_status,
        "source": row.source_snapshot_json,
    }


def _event_snapshot(row) -> dict:
    return {
        "event_id": str(row.event_id),
        "event_type": row.event_type,
        "causation_id": str(row.causation_id) if row.causation_id else None,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "last_error": _bounded(row.last_error or "", 500) or None,
    }


def _extraction_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "status": row.status,
        "source_url": row.source_url,
        "final_url": row.final_url,
        "title": row.title,
        "author": row.author,
        "published_at": row.published_at,
        "content_chars": len(row.content_text or ""),
        "content_excerpt": _bounded(row.content_text or "", 1500),
        "warnings": row.warnings_json,
        "error": row.error_message,
    }


def _enrichment_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "provider": row.provider_name,
        "status": row.status,
        "findings": row.findings_json[:10],
        "source_attribution": row.source_attribution_json[:10],
        "warnings": row.warnings_json,
        "error": row.error_message,
    }


def _sufficiency_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "stage": (row.input_snapshot_json or {}).get("stage"),
        "status": row.status,
        "score": row.score,
        "reasons": row.reasons_json,
        "minimum_needed": row.minimum_needed_json,
        "extraction_result_id": (row.input_snapshot_json or {}).get("extraction_result_id"),
        "enrichment_result_id": (row.input_snapshot_json or {}).get("enrichment_result_id"),
    }


def _brief_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "angle": row.angle,
        "key_facts": row.key_facts_json,
        "source_claims": row.source_claims_json,
        "unsafe_claims": row.unsafe_or_unverified_claims_json,
        "do_not_say": row.do_not_say_json,
        "evidence_ids": row.evidence_ids_json,
        "generation_metadata": row.generation_metadata_json,
    }


def _draft_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "title": row.title,
        "draft_text": _bounded(row.draft_text, 5000),
        "source_links": row.source_links_json,
        "warnings": row.warnings_json,
        "evidence_ids": row.evidence_ids_json,
        "generation_metadata": row.generation_metadata_json,
    }


def _quality_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "status": row.status,
        "score": row.score,
        "factuality_warnings": row.factuality_warnings_json,
        "unsupported_claims": row.unsupported_claims_json,
        "style_warnings": row.style_warnings_json,
        "required_revisions": row.required_revisions_json,
        "rubric": row.rubric_json,
        "evaluation_metadata": row.evaluation_metadata_json,
    }


def _media_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "status": row.status,
        "selected_media_asset_id": str(row.selected_media_asset_id) if row.selected_media_asset_id else None,
        "needs_generation": row.needs_generation,
        "provider": row.provider_name,
        "error": row.error_message,
    }


def _package_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "approval_status": row.approval_status,
        "package": row.package_json,
    }


def _dispatch_snapshot(row) -> dict:
    return {
        "artifact_id": str(row.id),
        "package_id": str(row.package_id),
        "status": row.status,
        "blocked_reason": row.blocked_reason,
    }


def _trace_snapshot(row) -> dict:
    duration_ms = None
    if row.finished_at and row.started_at:
        duration_ms = round((row.finished_at - row.started_at).total_seconds() * 1000, 2)
    return {
        "trace_id": str(row.id),
        "step": row.step_name,
        "status": row.status,
        "duration_ms": duration_ms,
        "model": row.model_name,
        "token_usage": row.token_usage_json,
        "input": row.input_snapshot_json,
        "output": row.output_snapshot_json,
        "error": row.error_message,
    }


def _claim_source_map(briefs: list[EditorialBrief]) -> list[dict]:
    mapped = []
    for brief in briefs:
        for fact in brief.key_facts_json or []:
            mapped.append({"claim": fact.get("claim"), "source_url": fact.get("source_url"), "kind": "primary"})
        for claim in brief.source_claims_json or []:
            mapped.append(
                {"claim": claim.get("claim"), "source_url": claim.get("source_url"), "kind": claim.get("source")}
            )
        for claim in brief.unsafe_or_unverified_claims_json or []:
            mapped.append(
                {"claim": claim.get("claim"), "source_url": claim.get("source_url"), "kind": "unverified"}
            )
    return mapped[:50]


def _load_human_reviews(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("human review file must map production run IDs to review objects")
    return payload


def _review_disagreement(reports: list[DraftQualityReport], human_review: dict | None) -> dict:
    if not reports or not human_review or not isinstance(human_review.get("scores"), dict):
        return {"status": "unavailable"}
    automated = reports[-1].rubric_json or {}
    human = human_review["scores"]
    aliases = {
        "evidence_coverage": "coverage_of_key_information",
        "headline_quality": "headline_hook_quality",
    }
    deltas = {}
    for key, value in automated.items():
        human_key = aliases.get(key, key)
        if isinstance(value, int) and isinstance(human.get(human_key), int):
            deltas[key] = value - human[human_key]
    return {
        "status": "compared",
        "score_deltas_automated_minus_human": deltas,
        "automated_recommendation": automated.get("recommendation"),
        "human_status": human_review.get("status"),
    }


def _bounded(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Controlled Step 7 content-production pilot")
    commands = root.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--topic")
    start.add_argument("--tone", default="professional")
    start.add_argument("--audience", default="Persian Telegram readers")
    start.add_argument("--max-candidates", type=int, default=3)
    start.add_argument("--content-item-id", action="append", default=[])
    start.add_argument("--allow-not-rewrite-ready", action="store_true")
    start.set_defaults(action=start_pilot)

    process = commands.add_parser("process")
    process.add_argument("--limit", type=int, default=20)
    process.add_argument("--max-batches", type=int, default=50)
    process.add_argument("--max-attempts", type=int, default=3)
    process.set_defaults(action=process_events)

    shortlist = commands.add_parser("approve-shortlist")
    shortlist.add_argument("--request-id", required=True)
    shortlist.add_argument("--selection-execution-id", required=True)
    shortlist.add_argument("--content-item-id", action="append", required=True)
    shortlist.set_defaults(action=approve_shortlist)

    package = commands.add_parser("approve-package")
    package.add_argument("--package-id", required=True)
    package.set_defaults(action=approve_package)

    report = commands.add_parser("report")
    report.add_argument("--request-id", required=True)
    report.add_argument("--human-reviews")
    report.add_argument("--output", default="../validation/pilot/step-7-evidence.json")
    report.set_defaults(action=write_report)
    return root


async def main() -> None:
    args = parser().parse_args()
    result = await args.action(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    asyncio.run(main())
