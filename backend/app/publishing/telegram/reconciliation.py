from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import exists, select

from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
)
from app.publishing.models import (
    Destination,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.service_contracts import (
    PublishValidationError,
    ReconciliationCase,
    ReconciliationDestination,
    ReconciliationOperationSummary,
)

_RECONCILIATION_AMBIGUITY_REASON = "Telegram send outcome is ambiguous and requires operator verification"


def _open_reconciliation_criterion():
    return exists(
        select(1)
        .select_from(PublishOperationReceipt)
        .where(
            PublishOperationReceipt.publish_job_id == PublishJob.id,
            PublishOperationReceipt.status == "ambiguous",
        )
    )


def _reconciliation_jobs_statement(*, publish_job_id: UUID | None = None):
    statement = (
        select(PublishJob, Destination)
        .join(Destination, Destination.id == PublishJob.destination_id)
        .where(
            Destination.platform == "telegram",
            _open_reconciliation_criterion(),
        )
    )
    if publish_job_id is not None:
        statement = statement.where(PublishJob.id == publish_job_id)
    return statement.order_by(PublishJob.updated_at.desc(), PublishJob.id.desc())


async def _reconciliation_receipts(
    session: Any,
    publish_job_ids: Sequence[UUID],
) -> dict[UUID, list[PublishOperationReceipt]]:
    if not publish_job_ids:
        return {}
    receipts = list(
        await session.scalars(
            select(PublishOperationReceipt)
            .where(PublishOperationReceipt.publish_job_id.in_(publish_job_ids))
            .order_by(
                PublishOperationReceipt.publish_job_id,
                PublishOperationReceipt.operation_index,
            )
        )
    )
    grouped: dict[UUID, list[PublishOperationReceipt]] = {}
    for receipt in receipts:
        grouped.setdefault(receipt.publish_job_id, []).append(receipt)
    for rows in grouped.values():
        rows.sort(key=lambda receipt: receipt.operation_index)
    return grouped


def _reconciliation_case(
    publish_job: PublishJob,
    destination: Destination,
    receipts: Sequence[PublishOperationReceipt],
) -> ReconciliationCase | None:
    ordered = sorted(receipts, key=lambda receipt: receipt.operation_index)
    ambiguous = next((receipt for receipt in ordered if receipt.status == "ambiguous"), None)
    if ambiguous is None:
        return None
    return ReconciliationCase(
        publish_job_id=publish_job.id,
        publish_status=publish_job.status,
        workflow_job_id=publish_job.workflow_job_id,
        platform_variant_revision_id=publish_job.platform_variant_revision_id,
        destination=ReconciliationDestination(
            id=destination.id,
            name=destination.name,
            target_ref=destination.target_ref,
        ),
        operations=[
            ReconciliationOperationSummary(
                operation_index=receipt.operation_index,
                operation_key=receipt.operation_key,
                method=receipt.method,
                request_hash=receipt.request_hash,
                status=receipt.status,
                attempt_count=receipt.attempt_count,
                remote_message_ids=list(receipt.remote_message_ids),
                sent_at=receipt.completed_at or receipt.ambiguous_at,
            )
            for receipt in ordered
        ],
        ambiguous_operation_key=ambiguous.operation_key,
        ambiguous_at=ambiguous.ambiguous_at,
        ambiguity_reason=_RECONCILIATION_AMBIGUITY_REASON,
    )


async def list_reconciliation_cases(session: Any) -> list[ReconciliationCase]:
    rows = (await session.execute(_reconciliation_jobs_statement())).all()
    receipt_rows = await _reconciliation_receipts(
        session,
        [publish_job.id for publish_job, _destination in rows],
    )
    cases: list[ReconciliationCase] = []
    for publish_job, destination in rows:
        case = _reconciliation_case(
            publish_job,
            destination,
            receipt_rows.get(publish_job.id, ()),
        )
        if case is not None:
            cases.append(case)
    return cases


async def get_reconciliation_case(
    session: Any,
    publish_job_id: UUID,
) -> ReconciliationCase | None:
    row = (await session.execute(_reconciliation_jobs_statement(publish_job_id=publish_job_id))).first()
    if row is None:
        return None
    publish_job, destination = row
    receipt_rows = await _reconciliation_receipts(session, (publish_job.id,))
    return _reconciliation_case(
        publish_job,
        destination,
        receipt_rows.get(publish_job.id, ()),
    )


def validate_publish_evidence(
    evidence_map: list[dict[str, Any]],
    snapshots: Iterable[Any],
) -> list[dict[str, Any]]:
    if not evidence_map:
        raise PublishValidationError("publish_evidence_missing", "Publish evidence is missing")
    indexed = {snapshot.id: snapshot for snapshot in snapshots}
    validated: list[dict[str, Any]] = []
    for raw in evidence_map:
        try:
            citation = TelegramEvidenceCitation.model_validate(raw)
        except Exception:
            raise PublishValidationError("publish_evidence_invalid", "Publish evidence is invalid") from None
        snapshot = indexed.get(citation.evidence_snapshot_id)
        if snapshot is None:
            raise PublishValidationError("publish_evidence_snapshot_missing", "Publish evidence snapshot is missing")
        text = snapshot.content_text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            expected = TelegramEvidenceCitation(
                evidence_snapshot_id=snapshot.id,
                evidence_key=snapshot.evidence_key,
                source_url=snapshot.source_url,
                locator=f"chars:0-{len(text)}",
                excerpt_sha256=snapshot.content_sha256,
            ).model_dump(mode="json")
        except Exception:
            raise PublishValidationError(
                "publish_evidence_snapshot_invalid", "Publish evidence snapshot is invalid"
            ) from None
        if digest != snapshot.content_sha256 or citation.model_dump(mode="json") != expected:
            raise PublishValidationError("publish_evidence_drift", "Publish evidence no longer matches its snapshot")
        validated.append(citation.model_dump(mode="json"))
    return validated


def validate_receipt_plan(receipts: Sequence[Any], operations: Sequence[Any]) -> None:
    expected = [(operation.index, operation.key, operation.method, operation.request_hash) for operation in operations]
    actual = [
        (receipt.operation_index, receipt.operation_key, receipt.method, receipt.request_hash)
        for receipt in sorted(receipts, key=lambda item: item.operation_index)
    ]
    if actual != expected:
        raise PublishValidationError("publish_plan_drift", "Publish operation plan drifted after receipt creation")


def ordered_receipt_remote_ids(receipts: Iterable[Any]) -> list[int]:
    remote_ids: list[int] = []
    for receipt in sorted(receipts, key=lambda item: item.operation_index):
        for message_id in receipt.remote_message_ids:
            if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
                raise PublishValidationError("remote_message_id_invalid", "Remote message IDs are invalid")
            if message_id in remote_ids:
                raise PublishValidationError("remote_message_id_duplicate", "Remote message IDs must be unique")
            remote_ids.append(message_id)
    if not remote_ids:
        raise PublishValidationError("remote_message_ids_missing", "Remote message IDs are missing")
    return remote_ids


def derive_telegram_permalink(target_ref: str, remote_message_ids: Sequence[int]) -> str | None:
    public_target = target_ref.removeprefix("@").strip()
    if not public_target or not public_target.replace("_", "").isalnum() or not remote_message_ids:
        return None
    return f"https://t.me/{public_target}/{remote_message_ids[0]}"


def validate_reconciliation(
    receipts: Sequence[Any],
    *,
    outcome: Literal["published", "not_published"],
    remote_message_ids: Sequence[int],
) -> Any:
    ambiguous = [receipt for receipt in receipts if receipt.status == "ambiguous"]
    if len(ambiguous) != 1:
        raise PublishValidationError("reconciliation_not_ambiguous", "Exactly one ambiguous operation is required")
    if outcome == "published":
        if any(receipt.status not in {"succeeded", "ambiguous"} for receipt in receipts):
            raise PublishValidationError(
                "reconciliation_incomplete",
                "Pending operations cannot be reconciled as published",
            )
        if not remote_message_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in remote_message_ids
        ):
            raise PublishValidationError(
                "reconciliation_remote_ids_invalid",
                "Verified remote message IDs are required",
            )
    else:
        if any(receipt.status not in {"succeeded", "pending", "ambiguous"} for receipt in receipts):
            raise PublishValidationError(
                "reconciliation_incomplete",
                "Unsafe operation states cannot be reconciled as not published",
            )
        if remote_message_ids:
            raise PublishValidationError(
                "reconciliation_remote_ids_forbidden",
                "Not-published outcome cannot include remote IDs",
            )
    return ambiguous[0]
