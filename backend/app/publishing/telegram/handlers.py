from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.faults import FaultInjector, NoopFaultInjector
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.types import JobExecution, job_payload_copy
from app.publishing.models import Destination, PublishJob, TelegramProxyProfile
from app.publishing.telegram.client import (
    TelegramAmbiguousError,
    TelegramPermanentError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.routing import (
    TelegramConfigurationError,
    check_proxy_reachability,
    validate_proxy_endpoint,
)
from app.publishing.telegram.service import publish_telegram


class _PublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_job_id: UUID


class _DestinationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: UUID


class _ProxyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proxy_id: UUID


@dataclass(frozen=True, slots=True)
class TelegramPublishHandlers:
    publish: Any
    destination_check: Any
    proxy_check: Any


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


@asynccontextmanager
async def _runtime(session, destination, client, secret_resolver, route_resolver):
    if route_resolver is None:
        token = await _resolve_secret(secret_resolver, destination.secret_ref)
        yield client, token
        return
    token = await route_resolver.destination_token(session, destination)
    async with route_resolver.client_for_destination(session, destination) as routed_client:
        yield routed_client, token


def _mapped_check_error(error: Exception) -> Exception:
    if isinstance(error, TelegramRateLimited):
        return RetryableJobError(
            code="telegram_destination_rate_limited",
            message="Telegram destination check was rate limited",
            retry_at=datetime.now(UTC) + timedelta(seconds=error.retry_after),
        )
    if isinstance(error, TelegramRetryableBeforeDispatch):
        return RetryableJobError(
            code="telegram_destination_connect_failed",
            message="Telegram destination check could not connect",
        )
    if isinstance(error, TelegramAmbiguousError):
        return NeedsReviewJobError(
            code="telegram_destination_check_ambiguous",
            message="Telegram destination check returned an ambiguous result",
        )
    if isinstance(error, TelegramConfigurationError):
        return PermanentJobError(code=error.code, message="Telegram route configuration is unavailable")
    if isinstance(error, PermanentJobError):
        return error
    if isinstance(error, TelegramPermanentError):
        return PermanentJobError(
            code="telegram_destination_check_failed",
            message="Telegram destination check failed",
        )
    return PermanentJobError(
        code="telegram_destination_check_failed",
        message="Telegram destination check failed",
    )


def build_telegram_publish_handlers(
    client: Any,
    secret_resolver: Any,
    *,
    route_resolver: Any | None = None,
    fault_injector: FaultInjector | None = None,
) -> TelegramPublishHandlers:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()

    async def publish(job: JobExecution, context: JobContext) -> dict[str, Any]:
        try:
            payload = _PublishPayload.model_validate(job_payload_copy(job))
        except Exception:
            raise PermanentJobError(
                code="telegram_publish_payload_invalid",
                message="Publish job payload is invalid",
            ) from None
        if route_resolver is None:
            return await publish_telegram(
                context.session,
                publish_job_id=payload.publish_job_id,
                client=client,
                secret_resolver=secret_resolver,
                fault_injector=injector,
            )
        publish_job = await context.session.get(PublishJob, payload.publish_job_id)
        destination = (
            await context.session.get(Destination, publish_job.destination_id) if publish_job is not None else None
        )
        if destination is None or destination.platform != "telegram":
            raise PermanentJobError(
                code="telegram_destination_missing",
                message="Telegram destination was not found",
            )
        try:
            async with _runtime(context.session, destination, client, secret_resolver, route_resolver) as (
                routed_client,
                token,
            ):
                await context.session.commit()
                return await publish_telegram(
                    context.session,
                    publish_job_id=payload.publish_job_id,
                    client=routed_client,
                    secret_resolver=lambda _reference: token,
                    expected_proxy_profile_id=destination.proxy_profile_id,
                    fault_injector=injector,
                )
        except TelegramConfigurationError as exc:
            raise PermanentJobError(code=exc.code, message="Telegram route configuration is unavailable") from None

    async def destination_check(job: JobExecution, context: JobContext) -> dict[str, Any]:
        try:
            payload = _DestinationPayload.model_validate(job_payload_copy(job))
        except Exception:
            raise PermanentJobError(
                code="telegram_destination_payload_invalid",
                message="Destination check payload is invalid",
            ) from None
        destination = await context.session.get(Destination, payload.destination_id)
        if destination is None or destination.platform != "telegram":
            raise PermanentJobError(
                code="telegram_destination_missing",
                message="Telegram destination was not found",
            )
        snapshot = (
            destination.target_ref,
            destination.secret_ref,
            destination.secret_id,
            destination.proxy_profile_id,
        )
        stages = {
            "proxy_health_status": "direct" if destination.proxy_profile_id is None else "checking",
            "telegram_health_status": "checking",
            "bot_health_status": "checking",
            "target_health_status": "checking",
            "administrator_status": "checking",
        }
        bot: dict[str, Any] | None = None
        chat: dict[str, Any] | None = None
        failure_code: str | None = None
        error: Exception | None = None
        await context.session.commit()
        try:
            if destination.proxy_profile_id is not None and route_resolver is not None:
                profile = await context.session.get(TelegramProxyProfile, destination.proxy_profile_id)
                if profile is None or not profile.enabled:
                    raise TelegramConfigurationError("telegram_proxy_not_ready")
                endpoint = await validate_proxy_endpoint(profile.host, profile.port, config=route_resolver.config)
                await check_proxy_reachability(endpoint, config=route_resolver.config)
                stages["proxy_health_status"] = "healthy"
            async with _runtime(context.session, destination, client, secret_resolver, route_resolver) as (
                routed_client,
                token,
            ):
                get_me = getattr(routed_client, "get_me", None)
                get_member = getattr(routed_client, "get_chat_member", None)
                if get_me is None or get_member is None:
                    chat = await routed_client.get_chat(destination.target_ref, token)
                    bot = {"id": None, "username": None}
                    member = {"administrator": True}
                else:
                    bot = await get_me(token)
                    stages["telegram_health_status"] = "healthy"
                    stages["bot_health_status"] = "healthy"
                    chat = await routed_client.get_chat(destination.target_ref, token)
                    stages["target_health_status"] = "healthy"
                    member = await get_member(destination.target_ref, bot["id"], token)
                stages["telegram_health_status"] = "healthy"
                stages["bot_health_status"] = "healthy"
                stages["target_health_status"] = "healthy"
                stages["administrator_status"] = (
                    "administrator" if member.get("administrator") is True else "not_administrator"
                )
                if stages["administrator_status"] != "administrator":
                    raise TelegramConfigurationError("telegram_bot_not_administrator")
        except Exception as exc:  # noqa: BLE001 - map all transport failures to safe codes
            error = _mapped_check_error(exc)
            failure_code = getattr(error, "code", "telegram_destination_check_failed")
            if stages["proxy_health_status"] == "checking":
                stages["proxy_health_status"] = "unhealthy"
                stages["telegram_health_status"] = "unchecked"
                stages["bot_health_status"] = "unchecked"
                stages["target_health_status"] = "unchecked"
                stages["administrator_status"] = "unchecked"
            elif stages["telegram_health_status"] == "checking":
                stages["telegram_health_status"] = "unhealthy"
                stages["bot_health_status"] = "unchecked"
                stages["target_health_status"] = "unchecked"
                stages["administrator_status"] = "unchecked"
            elif stages["bot_health_status"] == "checking":
                stages["bot_health_status"] = "unhealthy"
                stages["target_health_status"] = "unchecked"
                stages["administrator_status"] = "unchecked"
            elif stages["target_health_status"] == "checking":
                stages["target_health_status"] = "unhealthy"
                stages["administrator_status"] = "unchecked"
            elif stages["administrator_status"] == "checking":
                stages["administrator_status"] = "not_administrator"

        configuration_changed = False
        async with context.session.begin():
            current = await context.session.scalar(
                select(Destination).where(Destination.id == payload.destination_id).with_for_update()
            )
            configuration_changed = (
                current is None
                or (
                    current.target_ref,
                    current.secret_ref,
                    current.secret_id,
                    current.proxy_profile_id,
                )
                != snapshot
            )
            if current is not None:
                if configuration_changed:
                    current.health_status = "unknown"
                    current.failure_code = "telegram_destination_changed_during_check"
                else:
                    for field, value in stages.items():
                        setattr(current, field, value)
                    current.health_status = "healthy" if error is None else "unhealthy"
                    current.failure_code = failure_code
                    current.last_health_check_at = datetime.now(UTC)
                    if error is None and bot is not None and chat is not None:
                        current.verified_bot_id = bot.get("id")
                        current.verified_bot_username = bot.get("username")
                        current.verified_chat_id = chat.get("id")
                        current.verified_chat_title = chat.get("title")
                        current.verified_chat_type = chat.get("type")
        if configuration_changed:
            raise NeedsReviewJobError(
                code="telegram_destination_changed_during_check",
                message="Telegram destination changed during its health check",
            )
        if error is not None:
            raise error
        return {
            "destination_id": str(payload.destination_id),
            "health_status": "healthy",
            "proxy_health_status": stages["proxy_health_status"],
            "telegram_health_status": "healthy",
            "bot_health_status": "healthy",
            "target_health_status": "healthy",
            "administrator_status": "administrator",
        }

    async def proxy_check(job: JobExecution, context: JobContext) -> dict[str, Any]:
        try:
            payload = _ProxyPayload.model_validate(job_payload_copy(job))
        except Exception:
            raise PermanentJobError(
                code="telegram_proxy_payload_invalid",
                message="Proxy check payload is invalid",
            ) from None
        profile = await context.session.get(TelegramProxyProfile, payload.proxy_id)
        if profile is None:
            raise PermanentJobError(code="telegram_proxy_missing", message="Telegram proxy was not found")
        snapshot = (profile.proxy_type, profile.host, profile.port)
        await context.session.commit()
        error: TelegramConfigurationError | None = None
        try:
            config = route_resolver.config if route_resolver is not None else None
            endpoint = await validate_proxy_endpoint(
                profile.host,
                profile.port,
                **({"config": config} if config is not None else {}),
            )
            await check_proxy_reachability(endpoint, **({"config": config} if config is not None else {}))
        except TelegramConfigurationError as exc:
            error = exc
        changed = False
        async with context.session.begin():
            current = await context.session.scalar(
                select(TelegramProxyProfile).where(TelegramProxyProfile.id == payload.proxy_id).with_for_update()
            )
            changed = current is None or (current.proxy_type, current.host, current.port) != snapshot
            if current is not None:
                current.reachability_status = "unchecked" if changed else "healthy" if error is None else "unhealthy"
                current.failure_code = (
                    "telegram_proxy_changed_during_check" if changed else error.code if error else None
                )
                current.last_checked_at = datetime.now(UTC)
        if changed:
            raise NeedsReviewJobError(
                code="telegram_proxy_changed_during_check",
                message="Telegram proxy changed during its health check",
            )
        if error is not None:
            raise PermanentJobError(code=error.code, message="Telegram proxy check failed")
        return {"proxy_id": str(payload.proxy_id), "reachability_status": "healthy"}

    return TelegramPublishHandlers(
        publish=publish,
        destination_check=destination_check,
        proxy_check=proxy_check,
    )
