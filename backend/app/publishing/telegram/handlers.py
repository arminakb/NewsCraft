from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.publishing.models import Destination
from app.publishing.telegram.client import (
    TelegramAmbiguousError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.service import publish_telegram


class _PublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_job_id: UUID


class _DestinationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: UUID


@dataclass(frozen=True, slots=True)
class TelegramPublishHandlers:
    publish: Any
    destination_check: Any


async def _resolve_secret(resolver: Any, secret_ref: str) -> str:
    target = getattr(resolver, "resolve", None)
    if target is None and callable(resolver):
        target = resolver
    if target is None:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        )
    try:
        value = target(secret_ref)
        if inspect.isawaitable(value):
            value = await value
    except Exception:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        ) from None
    if not isinstance(value, str) or not value:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        )
    return value


def build_telegram_publish_handlers(client: Any, secret_resolver: Any) -> TelegramPublishHandlers:
    async def publish(job: Any, context: Any) -> dict[str, Any]:
        try:
            payload = _PublishPayload.model_validate(job.payload)
        except Exception:
            raise PermanentJobError(
                code="telegram_publish_payload_invalid",
                message="Publish job payload is invalid",
            ) from None
        return await publish_telegram(
            context.session,
            publish_job_id=payload.publish_job_id,
            client=client,
            secret_resolver=secret_resolver,
        )

    async def destination_check(job: Any, context: Any) -> dict[str, Any]:
        try:
            payload = _DestinationPayload.model_validate(job.payload)
        except Exception:
            raise PermanentJobError(
                code="telegram_destination_payload_invalid", message="Destination check payload is invalid"
            ) from None
        destination = await context.session.get(Destination, payload.destination_id)
        if destination is None or destination.platform != "telegram":
            raise PermanentJobError(code="telegram_destination_missing", message="Telegram destination was not found")
        secret_ref = destination.secret_ref
        target_ref = destination.target_ref
        await context.session.commit()
        error: Exception | None = None
        try:
            token = await _resolve_secret(secret_resolver, secret_ref)
            chat = await client.get_chat(target_ref, token)
        except PermanentJobError as exc:
            error = exc
        except TelegramRateLimited as exc:
            error = RetryableJobError(
                code="telegram_destination_rate_limited",
                message="Telegram destination check was rate limited",
                retry_at=datetime.now(UTC) + timedelta(seconds=exc.retry_after),
            )
        except TelegramRetryableBeforeDispatch:
            error = RetryableJobError(
                code="telegram_destination_connect_failed",
                message="Telegram destination check could not connect",
            )
        except TelegramAmbiguousError:
            error = NeedsReviewJobError(
                code="telegram_destination_check_ambiguous",
                message="Telegram destination check returned an ambiguous result",
            )
        except Exception:
            error = PermanentJobError(
                code="telegram_destination_check_failed",
                message="Telegram destination check failed",
            )
        if error is not None:
            configuration_changed = False
            async with context.session.begin():
                destination = await context.session.scalar(
                    select(Destination)
                    .where(Destination.id == payload.destination_id)
                    .with_for_update()
                )
                configuration_changed = destination is None
                if destination is not None:
                    configuration_changed = (
                        destination.platform != "telegram"
                        or destination.target_ref != target_ref
                        or destination.secret_ref != secret_ref
                    )
                    destination.health_status = "unknown" if configuration_changed else "unhealthy"
                    destination.last_health_check_at = datetime.now(UTC)
            if configuration_changed:
                raise NeedsReviewJobError(
                    code="telegram_destination_changed_during_check",
                    message="Telegram destination changed during its health check",
                )
            raise error
        configuration_changed = False
        async with context.session.begin():
            destination = await context.session.scalar(
                select(Destination)
                .where(Destination.id == payload.destination_id)
                .with_for_update()
            )
            configuration_changed = destination is None
            if destination is not None:
                configuration_changed = (
                    destination.platform != "telegram"
                    or destination.target_ref != target_ref
                    or destination.secret_ref != secret_ref
                )
                destination.health_status = "unknown" if configuration_changed else "healthy"
                destination.last_health_check_at = datetime.now(UTC)
        if configuration_changed:
            raise NeedsReviewJobError(
                code="telegram_destination_changed_during_check",
                message="Telegram destination changed during its health check",
            )
        return {"destination_id": str(payload.destination_id), "health_status": "healthy", "chat": chat}

    return TelegramPublishHandlers(publish=publish, destination_check=destination_check)
