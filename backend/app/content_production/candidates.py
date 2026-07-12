from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.content_production.repository import ContentProductionRepository
from app.db.models import CandidateShortlist, ContentItem, ContentProductionRequest

_MIN_EFFECTIVE_SORT_TIME = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class CandidateDecision:
    content_item: ContentItem
    score: Decimal
    selection_reason: dict
    risk_flags: list[str]
    source_snapshot: dict


class CandidateSelectionService:
    def __init__(self, session):
        self.session = session

    async def prepare_shortlist(
        self,
        request: ContentProductionRequest,
        *,
        command_id: UUID | None = None,
    ) -> list[CandidateShortlist]:
        rows = await self.session.scalars(select(ContentItem))
        items = list(rows)
        pilot_ids = set((request.constraints_json or {}).get("pilot_content_item_ids", []))
        if pilot_ids:
            items = [item for item in items if str(item.id) in pilot_ids]
        decisions = rank_candidate_items(items, request)
        repository = ContentProductionRepository(self.session)
        shortlist: list[CandidateShortlist] = []
        for index, decision in enumerate(decisions[: request.max_candidates or 10], start=1):
            shortlist.append(
                await repository.add_shortlist_candidate(
                    request_id=request.id,
                    selection_execution_id=command_id or request.id,
                    content_item_id=decision.content_item.id,
                    rank=index,
                    score=decision.score,
                    selection_reason_json=decision.selection_reason,
                    risk_flags_json=decision.risk_flags,
                    source_snapshot_json=decision.source_snapshot,
                    command_id=command_id,
                )
            )
        request.status = "shortlist_approval_pending" if shortlist else "shortlist_ready"
        await self.session.flush()
        return shortlist


def rank_candidate_items(
    items: list[ContentItem],
    request: ContentProductionRequest,
    *,
    now: datetime | None = None,
) -> list[CandidateDecision]:
    now = now or datetime.now(UTC)
    decisions = [_score_candidate(item, request, now) for item in items]
    viable = [decision for decision in decisions if _is_viable(decision, request)]
    ordered = sorted(viable, key=lambda decision: decision.content_item.id.int)
    ordered.sort(key=lambda decision: _effective_sort_time(decision.content_item), reverse=True)
    ordered.sort(key=lambda decision: decision.score, reverse=True)
    return ordered


def _effective_sort_time(item: ContentItem) -> datetime:
    value = item.sort_at or item.created_at
    if value is None:
        return _MIN_EFFECTIVE_SORT_TIME
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _score_candidate(item: ContentItem, request: ContentProductionRequest, now: datetime) -> CandidateDecision:
    base_score = Decimal(item.score or 0)
    reasons: list[str] = ["score"]
    risk_flags: list[str] = []

    if item.is_rewrite_ready:
        base_score += Decimal("12")
        reasons.append("rewrite_ready")
    elif request.require_rewrite_ready:
        risk_flags.append("not_rewrite_ready")

    if item.primary_image_id:
        base_score += Decimal("4")
        reasons.append("has_primary_media")
    elif request.require_media:
        risk_flags.append("missing_media")

    if item.duplicate_of_id:
        base_score -= Decimal("50")
        risk_flags.append("duplicate")

    if item.content_type in {"promo", "low_signal"}:
        base_score -= Decimal("40")
        risk_flags.append(item.content_type)

    if item.freshness_bucket in {"stale", "archive"}:
        base_score -= Decimal("15")
        risk_flags.append(item.freshness_bucket)

    topic_match = _topic_match_score(item, request.topic)
    if request.topic:
        if topic_match:
            base_score += Decimal(topic_match)
            reasons.append("topic_match")
        else:
            risk_flags.append("topic_mismatch")

    if item.source_tier in {"A", "B"}:
        base_score += Decimal("6" if item.source_tier == "A" else "3")
        reasons.append("trusted_source_tier")

    return CandidateDecision(
        content_item=item,
        score=max(base_score, Decimal("0")),
        selection_reason={
            "signals": reasons,
            "base_score": item.score or 0,
            "topic": request.topic,
            "evaluated_at": now.isoformat(),
        },
        risk_flags=risk_flags,
        source_snapshot={
            "title": item.title,
            "canonical_url": item.canonical_url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "source_tier": item.source_tier,
            "freshness_bucket": item.freshness_bucket,
            "content_type": item.content_type,
            "is_rewrite_ready": item.is_rewrite_ready,
            "primary_image_id": str(item.primary_image_id) if item.primary_image_id else None,
        },
    )


def _is_viable(decision: CandidateDecision, request: ContentProductionRequest) -> bool:
    flags = set(decision.risk_flags)
    if request.require_rewrite_ready and "not_rewrite_ready" in flags:
        return False
    if request.require_media and "missing_media" in flags:
        return False
    if "topic_mismatch" in flags:
        return False
    return not flags.intersection({"duplicate", "promo", "low_signal", "archive"})


def _topic_match_score(item: ContentItem, topic: str | None) -> int:
    if not topic:
        return 0
    normalized_topic = topic.casefold()
    searchable = " ".join(
        value
        for value in (
            item.title or "",
            item.summary or "",
            item.content_text or "",
            " ".join(item.tags or []),
        )
        if value
    ).casefold()
    if normalized_topic in searchable:
        return 15
    topic_terms = [term for term in normalized_topic.replace("-", " ").split() if len(term) >= 3]
    return min(sum(1 for term in topic_terms if term in searchable) * 5, 10)


class ShortlistApprovalService:
    def __init__(self, session):
        self.session = session

    async def approve(
        self,
        request_id: UUID,
        selection_execution_id: UUID,
        content_item_ids: list[UUID],
        *,
        previous_state: dict[str, str] | None = None,
    ) -> list[CandidateShortlist]:
        candidates = await self._matching_candidates(request_id, selection_execution_id, content_item_ids)
        now = datetime.now(UTC)
        for candidate in candidates:
            if previous_state is not None:
                previous_state[str(candidate.content_item_id)] = candidate.approval_status
            candidate.approval_status = "approved"
            candidate.approved_at = now
        await self.session.flush()
        return candidates

    async def reject(
        self,
        request_id: UUID,
        selection_execution_id: UUID,
        content_item_ids: list[UUID],
        *,
        previous_state: dict[str, str] | None = None,
    ) -> list[CandidateShortlist]:
        candidates = await self._matching_candidates(request_id, selection_execution_id, content_item_ids)
        now = datetime.now(UTC)
        for candidate in candidates:
            if previous_state is not None:
                previous_state[str(candidate.content_item_id)] = candidate.approval_status
            candidate.approval_status = "rejected"
            candidate.rejected_at = now
        await self.session.flush()
        return candidates

    async def _matching_candidates(
        self,
        request_id: UUID,
        selection_execution_id: UUID,
        content_item_ids: list[UUID],
    ) -> list[CandidateShortlist]:
        rows = await self.session.scalars(
            select(CandidateShortlist).where(
                CandidateShortlist.request_id == request_id,
                CandidateShortlist.selection_execution_id == selection_execution_id,
                CandidateShortlist.content_item_id.in_(content_item_ids),
            )
        )
        selected_ids = set(content_item_ids)
        candidates = [
            candidate
            for candidate in rows
            if candidate.request_id == request_id
            and candidate.selection_execution_id == selection_execution_id
            and candidate.content_item_id in selected_ids
        ]
        if len(candidates) != len(set(content_item_ids)):
            raise LookupError("one or more shortlist candidates were not found")
        return candidates
