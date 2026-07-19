from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.automations.telegram.handlers import enqueue_telegram_publish_intent
from app.core.faults import InjectedFault, ScriptedFaultInjector
from app.core.outbound_proxy import build_outbound_http_client
from app.core.secrets import FileSecretResolver
from app.db.session import async_session
from app.generation.models import PlatformVariantRevision
from app.generation.telegram_schema import TelegramVariantContent
from app.jobs.errors import NeedsReviewJobError
from app.jobs.models import AutomationControl, RuntimeHeartbeat, WorkflowJob
from app.publishing.models import Destination, Publication, PublishJob, PublishOperationReceipt
from app.publishing.telegram.client import TelegramBotClient
from app.publishing.telegram.service import _revision_dispatch, derive_telegram_permalink, publish_telegram

_MARKER = re.compile(r"^NC-STAGING-[A-Z0-9-]{8,80}$")
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:/-]{0,127}$")
_LIVE_SCENARIOS = {"success", "ambiguity"}


class StagingQualificationError(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class _RecordingTelegramClient:
    def __init__(self, client: TelegramBotClient) -> None:
        self.client = client
        self.send_count = 0
        self.results: list[Any] = []

    async def get_chat(self, target_ref: str, token: str) -> dict[str, Any]:
        return await self.client.get_chat(target_ref, token)

    async def execute(self, operation: Any, token: str) -> Any:
        self.send_count += 1
        result = await self.client.execute(operation, token)
        self.results.append(result)
        return result


def _validate_common_arguments(args: argparse.Namespace) -> None:
    if os.environ.get("NEWSCRAFT_LIVE_TELEGRAM_STAGING") != "authorized":
        raise StagingQualificationError("NEWSCRAFT_LIVE_TELEGRAM_STAGING=authorized is required")
    if _MARKER.fullmatch(args.marker) is None:
        raise StagingQualificationError("marker must be a unique NC-STAGING-* identifier")
    if re.fullmatch(r"[0-9a-f]{64}", args.content_hash) is None:
        raise StagingQualificationError("content hash must be an exact SHA-256 value")
    try:
        UUID(args.destination_id)
        UUID(args.revision_id)
    except ValueError:
        raise StagingQualificationError("destination and revision IDs must be UUIDs") from None
    if (
        isinstance(args.expected_chat_id, bool)
        or not isinstance(args.expected_chat_id, int)
        or args.expected_chat_id == 0
        or isinstance(args.expected_operation_count, bool)
        or not isinstance(args.expected_operation_count, int)
        or not 1 <= args.expected_operation_count <= 20
        or isinstance(args.expected_remote_message_count, bool)
        or not isinstance(args.expected_remote_message_count, int)
        or not 1 <= args.expected_remote_message_count <= 20
    ):
        raise StagingQualificationError("expected chat and result counts are invalid")
    if args.scenario in _LIVE_SCENARIOS and not args.confirm_live_send:
        raise StagingQualificationError("live scenarios require --confirm-live-send")
    if args.scenario == "verify" and not args.remote_message_ids:
        raise StagingQualificationError("verification requires observed remote message IDs")
    if (
        not isinstance(args.observer_one, str)
        or not isinstance(args.observer_two, str)
        or not args.observer_one.strip()
        or not args.observer_two.strip()
        or args.observer_one == args.observer_two
    ):
        raise StagingQualificationError("two distinct observers are required")
    if any(
        _SAFE_REFERENCE.fullmatch(value) is None
        for value in (args.authorization_ticket, args.observer_one, args.observer_two)
    ):
        raise StagingQualificationError("authorization and observer references must be safe identifiers")
    if len(args.expected_target_ref) > 255 or not 1 <= len(args.expected_chat_title) <= 255:
        raise StagingQualificationError("authorized channel identity is invalid")
    if args.scenario == "verify" and _SAFE_REFERENCE.fullmatch(args.observation_ticket) is None:
        raise StagingQualificationError("verification requires a safe observation ticket")


async def _ensure_no_active_publishing_worker(session: Any, *, now: datetime) -> None:
    rows = list(
        await session.scalars(
            select(RuntimeHeartbeat).where(
                RuntimeHeartbeat.component_type == "worker",
                RuntimeHeartbeat.observed_at >= now - timedelta(minutes=2),
            )
        )
    )
    if any("publishing" in (row.capabilities or []) for row in rows):
        raise StagingQualificationError("stop the publishing worker before the controlled staging run")


async def _ensure_schema_head(session: Any) -> None:
    connection = await session.connection()
    current = await connection.run_sync(lambda sync: set(MigrationContext.configure(sync).get_current_heads()))
    expected = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
    if current != expected:
        raise StagingQualificationError("staging database is not at the repository migration head")


def _revision_marker(content: TelegramVariantContent, marker: str) -> None:
    if content.body.count(marker) != 1:
        raise StagingQualificationError("exactly one expected marker must appear in the revision body")


async def _load_preflight(
    args: argparse.Namespace,
) -> tuple[Destination, PlatformVariantRevision, TelegramVariantContent]:
    now = datetime.now(UTC)
    async with async_session() as session:
        await _ensure_schema_head(session)
        await _ensure_no_active_publishing_worker(session, now=now)
        destination = await session.get(Destination, UUID(args.destination_id))
        revision = await session.get(PlatformVariantRevision, UUID(args.revision_id))
        control = await session.get(AutomationControl, "global")
        if destination is None or destination.platform != "telegram":
            raise StagingQualificationError("staging destination was not found")
        if destination.target_ref != args.expected_target_ref:
            raise StagingQualificationError("destination target does not match the authorized target")
        if not destination.enabled or destination.health_status != "healthy":
            raise StagingQualificationError("staging destination must be enabled and healthy")
        if destination.secret_ref != "TELEGRAM_STAGING_TOKEN":
            raise StagingQualificationError("staging destination must use the dedicated token reference")
        if bool((destination.settings or {}).get("allow_auto_publish")):
            raise StagingQualificationError("staging destination must not allow automatic publishing")
        if revision is None or revision.content_hash != args.content_hash:
            raise StagingQualificationError("revision or exact content hash does not match")
        try:
            content = TelegramVariantContent.model_validate(revision.content)
        except ValueError:
            raise StagingQualificationError("revision content is invalid") from None
        _revision_marker(content, args.marker)
        if revision.approval_state != "approved" or content.dry_run:
            raise StagingQualificationError("staging revision must be approved and non-dry-run")
        if control is None:
            raise StagingQualificationError("global automation control is unavailable")
        if args.scenario == "dry-run" and not control.dry_run:
            raise StagingQualificationError("dry-run scenario requires global dry-run to be enabled")
        if args.scenario in _LIVE_SCENARIOS and (control.dry_run or control.global_pause):
            raise StagingQualificationError("live scenario requires dry-run and global pause to be off")
        dispatch = await _revision_dispatch(session, revision)
        if dispatch is None:
            raise StagingQualificationError("revision must have exact route provenance")
        return destination, revision, content


async def _enqueue(args: argparse.Namespace) -> UUID:
    async with async_session() as session:
        async with session.begin():
            destination = await session.get(Destination, UUID(args.destination_id))
            revision = await session.get(PlatformVariantRevision, UUID(args.revision_id))
            dispatch = await _revision_dispatch(session, revision) if revision is not None else None
            if destination is None or revision is None or dispatch is None:
                raise StagingQualificationError("staging publish context changed after preflight")
            publish_job = await enqueue_telegram_publish_intent(
                session,
                revision=revision,
                destination=destination,
                dispatch=dispatch if dispatch.variant_revision_id == revision.id else None,
            )
        return publish_job.id


async def _state(publish_job_id: UUID) -> dict[str, Any]:
    async with async_session() as session:
        job = await session.get(PublishJob, publish_job_id)
        workflow = await session.get(WorkflowJob, job.workflow_job_id) if job and job.workflow_job_id else None
        publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job_id))
        receipts = list(
            await session.scalars(
                select(PublishOperationReceipt)
                .where(PublishOperationReceipt.publish_job_id == publish_job_id)
                .order_by(PublishOperationReceipt.operation_index)
            )
        )
        return {
            "publish_job_id": str(publish_job_id),
            "publish_status": job.status if job else None,
            "workflow_job_id": str(workflow.id) if workflow else None,
            "workflow_status": str(workflow.status) if workflow else None,
            "publication_id": str(publication.id) if publication else None,
            "publication_payload_hash": publication.payload_hash if publication else None,
            "publication_remote_message_ids": list(publication.remote_message_ids) if publication else [],
            "publication_permalink": publication.permalink if publication else None,
            "reconciliation_status": publication.reconciliation_status if publication else None,
            "receipts": [
                {
                    "operation_index": item.operation_index,
                    "operation_key": item.operation_key,
                    "method": item.method,
                    "request_hash": item.request_hash,
                    "status": item.status,
                    "attempt_count": item.attempt_count,
                    "remote_message_ids": list(item.remote_message_ids),
                    "response_metadata": dict(item.response_metadata or {}),
                    "ambiguous_at": item.ambiguous_at.isoformat() if item.ambiguous_at else None,
                }
                for item in receipts
            ],
        }


async def _publish_once(
    publish_job_id: UUID,
    *,
    client: Any,
    resolver: FileSecretResolver,
    fault_injector: Any | None = None,
) -> dict[str, Any]:
    async with async_session() as session:
        return await publish_telegram(
            session,
            publish_job_id=publish_job_id,
            client=client,
            secret_resolver=resolver,
            fault_injector=fault_injector,
        )


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    destination, _revision, _content = await _load_preflight(args)
    resolver = FileSecretResolver(args.secret_root)
    token = resolver.resolve(destination.secret_ref)
    http = build_outbound_http_client(timeout=30)
    recorder = _RecordingTelegramClient(TelegramBotClient(http))
    try:
        chat = await recorder.get_chat(destination.target_ref, token)
        if chat.get("id") != args.expected_chat_id or chat.get("title") != args.expected_chat_title:
            raise StagingQualificationError("Telegram getChat identity does not match the authorized channel")
        if chat.get("type") != "channel":
            raise StagingQualificationError("authorized staging target must be a private channel")
        publish_job_id = await _enqueue(args)
        injected = None
        if args.scenario == "ambiguity":
            injected = ScriptedFaultInjector({"telegram.after_send_before_receipt": 1})
        primary_error = None
        try:
            await _publish_once(
                publish_job_id,
                client=recorder,
                resolver=resolver,
                fault_injector=injected,
            )
        except InjectedFault:
            primary_error = "injected_after_send_before_receipt"
        except NeedsReviewJobError as exc:
            primary_error = exc.code
        first_send_count = recorder.send_count
        replay_error = None
        try:
            await _publish_once(
                publish_job_id,
                client=recorder,
                resolver=resolver,
            )
        except NeedsReviewJobError as exc:
            replay_error = exc.code
        state = await _state(publish_job_id)
    finally:
        await http.aclose()

    if args.scenario == "dry-run":
        if first_send_count != 0 or recorder.send_count != 0 or state["publication_id"] is not None:
            raise StagingQualificationError("dry-run attempted a remote send or created a publication")
    elif args.scenario == "success":
        observed_ids = [remote_id for result in recorder.results for remote_id in result.remote_message_ids]
        expected_permalink = derive_telegram_permalink(destination.target_ref, observed_ids)
        if (
            first_send_count != args.expected_operation_count
            or recorder.send_count != first_send_count
            or len(observed_ids) != args.expected_remote_message_count
            or len(observed_ids) != len(set(observed_ids))
            or any(remote_id <= 0 for remote_id in observed_ids)
        ):
            raise StagingQualificationError("success replay produced an additional remote send")
        if (
            state["publication_id"] is None
            or state["publication_payload_hash"] != args.content_hash
            or state["publication_remote_message_ids"] != observed_ids
            or state["publication_permalink"] != expected_permalink
            or state["reconciliation_status"] != "confirmed"
        ):
            raise StagingQualificationError("successful remote send has no exact local publication")
    elif args.scenario == "ambiguity":
        ambiguous = [item for item in state["receipts"] if item["status"] == "ambiguous"]
        if first_send_count != 1 or recorder.send_count != 1 or len(ambiguous) != 1:
            raise StagingQualificationError("ambiguity drill did not stop after one remote send")
        if state["publication_id"] is not None or replay_error != "telegram_publish_reconciliation_required":
            raise StagingQualificationError("ambiguity drill did not fence publication and replay")
    return {
        "schema_version": "live-telegram-staging-report-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "scenario": args.scenario,
        "authorization_ticket": args.authorization_ticket,
        "observers": sorted([args.observer_one, args.observer_two]),
        "destination_id": args.destination_id,
        "expected_target_ref": args.expected_target_ref,
        "verified_chat": chat,
        "revision_id": args.revision_id,
        "content_hash": args.content_hash,
        "marker": args.marker,
        "publish": state,
        "remote_send_count": recorder.send_count,
        "remote_ids_observed_before_fault": [
            remote_id for result in recorder.results for remote_id in result.remote_message_ids
        ],
        "primary_error": primary_error,
        "replay_error": replay_error,
        "requires_manual_channel_verification": args.scenario in _LIVE_SCENARIOS,
    }


async def _verify(args: argparse.Namespace) -> dict[str, Any]:
    destination, _revision, _content = await _load_preflight(args)
    try:
        observed = [int(part) for part in args.remote_message_ids.split(",")]
    except ValueError:
        raise StagingQualificationError("observed remote message IDs must be integers") from None
    if (
        any(value <= 0 for value in observed)
        or len(observed) != len(set(observed))
        or len(observed) != args.expected_remote_message_count
    ):
        raise StagingQualificationError("observed remote message IDs must be unique positive integers")
    resolver = FileSecretResolver(args.secret_root)
    token = resolver.resolve(destination.secret_ref)
    http = build_outbound_http_client(timeout=30)
    try:
        chat = await TelegramBotClient(http).get_chat(destination.target_ref, token)
    finally:
        await http.aclose()
    if chat.get("id") != args.expected_chat_id or chat.get("title") != args.expected_chat_title:
        raise StagingQualificationError("Telegram getChat identity changed before evidence verification")
    async with async_session() as session:
        expected_permalink = derive_telegram_permalink(destination.target_ref, observed)
        publication = await session.scalar(
            select(Publication).where(
                Publication.destination_id == destination.id,
                Publication.platform_variant_revision_id == UUID(args.revision_id),
            )
        )
        if (
            publication is None
            or publication.payload_hash != args.content_hash
            or publication.reconciliation_status != "confirmed"
            or list(publication.remote_message_ids) != observed
            or publication.permalink != expected_permalink
        ):
            raise StagingQualificationError("manual observation does not match confirmed local publication")
        state = await _state(publication.publish_job_id)
    return {
        "schema_version": "live-telegram-staging-verification-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "scenario": "verify",
        "authorization_ticket": args.authorization_ticket,
        "observers": sorted([args.observer_one, args.observer_two]),
        "observation_ticket": args.observation_ticket,
        "destination_id": args.destination_id,
        "verified_chat": chat,
        "revision_id": args.revision_id,
        "content_hash": args.content_hash,
        "marker": args.marker,
        "observed_remote_message_ids": observed,
        "publish": state,
        "exactly_one_remote_marker_confirmed": args.confirm_exactly_one_remote_marker,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an explicitly authorized Telegram staging qualification")
    parser.add_argument("--scenario", choices=("dry-run", "success", "ambiguity", "verify"), required=True)
    parser.add_argument("--destination-id", required=True)
    parser.add_argument("--revision-id", required=True)
    parser.add_argument("--content-hash", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--expected-target-ref", required=True)
    parser.add_argument("--expected-chat-id", type=int, required=True)
    parser.add_argument("--expected-chat-title", required=True)
    parser.add_argument("--authorization-ticket", required=True)
    parser.add_argument("--observer-one", default="")
    parser.add_argument("--observer-two", default="")
    parser.add_argument("--secret-root", type=Path, default=Path("/run/secrets"))
    parser.add_argument("--signing-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-live-send", action="store_true")
    parser.add_argument("--expected-operation-count", type=int, default=1)
    parser.add_argument("--expected-remote-message-count", type=int, default=1)
    parser.add_argument("--remote-message-ids", default="")
    parser.add_argument("--observation-ticket", default="")
    parser.add_argument("--confirm-exactly-one-remote-marker", action="store_true")
    parser.add_argument("--evidence-json", default="")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.evidence_json:
        try:
            evidence = json.loads(args.evidence_json)
        except json.JSONDecodeError:
            raise SystemExit("evidence JSON is invalid") from None
        if not isinstance(evidence, dict):
            raise SystemExit("evidence JSON must be an object")
        allowed = {
            "observer_one",
            "observer_two",
            "remote_message_ids",
            "observation_ticket",
            "expected_operation_count",
            "expected_remote_message_count",
            "confirm_exactly_one_remote_marker",
        }
        if set(evidence) - allowed:
            raise SystemExit("evidence JSON contains unsupported fields")
        for key, value in evidence.items():
            setattr(args, key, value)
    _validate_common_arguments(args)
    if args.scenario == "verify" and not args.confirm_exactly_one_remote_marker:
        raise SystemExit("verification requires --confirm-exactly-one-remote-marker")
    report = asyncio.run(_verify(args) if args.scenario == "verify" else _run(args))
    report["report_sha256"] = _hash(report)
    report["signature"] = {
        "algorithm": "HMAC-SHA256",
        "value": hmac.new(
            args.signing_key_file.read_bytes(),
            report["report_sha256"].encode(),
            hashlib.sha256,
        ).hexdigest(),
    }
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)


if __name__ == "__main__":
    main()
