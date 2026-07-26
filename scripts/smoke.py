#!/usr/bin/env python3
"""Deterministic, credential-free HTTP acceptance driver for NewsCraft."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

PLATFORMS = ("telegram", "instagram", "x", "blog")
STEPS = (
    "health",
    "configure",
    "manual_intake",
    "collect",
    "research",
    "generate_four_platforms",
    "edit_and_approve",
    "telegram_dry_run",
    "export",
    "manual_plan",
    "pause_and_resume",
    "history",
    "diagnostics",
)
EXPECTED_RUNTIME_COMPONENTS = frozenset({"worker-source-generation", "worker-publishing", "scheduler"})
EXPECTED_QUEUE_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "needs_review", "cancelled"})
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "needs_review", "cancelled"})
ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
CONTROL_RESTORE_RESERVE_SECONDS = 10.0


class SmokeError(RuntimeError):
    """A safe, reportable smoke failure with no server response material."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SmokeInvariantError(SmokeError):
    pass


class SmokeHTTPError(SmokeError):
    pass


class SmokeTimeoutError(SmokeError):
    pass


@dataclass(frozen=True, slots=True)
class HTTPResult:
    status: int
    data: object


@dataclass(frozen=True, slots=True)
class HTTPBytesResult:
    status: int
    data: bytes


@dataclass(frozen=True, slots=True)
class StepEvidence:
    ids: Mapping[str, str | list[str] | int] = field(default_factory=dict)
    statuses: Mapping[str, str] = field(default_factory=dict)
    invariants: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SmokeRunResult:
    steps: list[str]
    failed: list[str]
    report_path: Path


def _as_dict(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SmokeInvariantError(code)
    return value


def _as_list(value: object, code: str) -> list[Any]:
    if not isinstance(value, list):
        raise SmokeInvariantError(code)
    return value


def _require(condition: object, code: str) -> None:
    if not condition:
        raise SmokeInvariantError(code)


def _required_id(value: object, code: str) -> str:
    _require(isinstance(value, str) and bool(value), code)
    try:
        return str(UUID(str(value)))
    except ValueError:
        raise SmokeInvariantError(code) from None


def _required_hash(value: object, code: str) -> str:
    _require(isinstance(value, str) and SHA256_PATTERN.fullmatch(value), code)
    return str(value)


def _parse_time(value: object, code: str) -> datetime:
    _require(isinstance(value, str), code)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise SmokeInvariantError(code) from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed.astimezone(UTC)


class SmokeDriver:
    """Run the locked local acceptance sequence through the public HTTP API."""

    def __init__(
        self,
        *,
        base_url: str,
        output_dir: str | Path,
        provider: str = "fake",
        telegram_mode: str = "dry-run",
        timeout_seconds: float = 300,
        poll_interval_seconds: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP origin without credentials")
        if provider != "fake":
            raise ValueError("the deterministic smoke driver requires provider=fake")
        if telegram_mode != "dry-run":
            raise ValueError("the deterministic smoke driver requires telegram-mode=dry-run")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")

        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.provider = provider
        self.telegram_mode = telegram_mode
        self.timeout_seconds = float(timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._clock = clock
        self._sleeper = sleeper
        self._now = now or (lambda: datetime.now(UTC))
        started = self._now().astimezone(UTC)
        self.run_id = f"smoke-{started.strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(4)}"
        self.report_path = self.output_dir / f"{self.run_id}.json"
        self._started_at = started
        self._deadline: float | None = None
        self._current_step = "setup"
        self._mutation_count = 0
        self._state: dict[str, Any] = {}
        self._step_reports: list[dict[str, object]] = []
        self._failed: list[str] = []
        self._cleanup_failure_code: str | None = None

    def run(self) -> SmokeRunResult:
        if self._deadline is not None:
            raise RuntimeError("SmokeDriver instances can run only once")
        self._deadline = self._clock() + self.timeout_seconds
        operations = (
            self._health,
            self._configure,
            self._manual_intake,
            self._collect,
            self._research,
            self._generate_four_platforms,
            self._edit_and_approve,
            self._telegram_dry_run,
            self._export,
            self._manual_plan,
            self._pause_and_resume,
            self._history,
            self._diagnostics,
        )
        try:
            for name, operation in zip(STEPS, operations, strict=True):
                self._current_step = name
                started = self._clock()
                try:
                    self._remaining()
                    evidence = operation()
                except Exception as exc:  # The report intentionally omits exception text.
                    duration_ms = max(0, int((self._clock() - started) * 1_000))
                    code = exc.code if isinstance(exc, SmokeError) else "unexpected_error"
                    self._step_reports.append(
                        {
                            "name": name,
                            "status": "failed",
                            "duration_ms": duration_ms,
                            "failure_code": code,
                            "ids": {},
                            "statuses": {},
                            "invariants": [],
                        }
                    )
                    self._failed.append(name)
                    break
                duration_ms = max(0, int((self._clock() - started) * 1_000))
                self._step_reports.append(
                    {
                        "name": name,
                        "status": "succeeded",
                        "duration_ms": duration_ms,
                        "ids": dict(evidence.ids),
                        "statuses": dict(evidence.statuses),
                        "invariants": list(evidence.invariants),
                    }
                )
        finally:
            if self._state.get("control_restore_required") is True:
                previous_step = self._current_step
                self._current_step = "cleanup"
                try:
                    self._restore_original_control()
                except Exception as exc:
                    self._cleanup_failure_code = exc.code if isinstance(exc, SmokeError) else "unexpected_error"
                    self._failed.append("cleanup")
                finally:
                    self._current_step = previous_step

        self._write_report()
        return SmokeRunResult(
            steps=[str(item["name"]) for item in self._step_reports],
            failed=list(self._failed),
            report_path=self.report_path,
        )

    def _write_report(self) -> None:
        finished_at = self._now().astimezone(UTC)
        report = {
            "schema_version": "newscraft-smoke-v1",
            "run_id": self.run_id,
            "provider": self.provider,
            "telegram_mode": self.telegram_mode,
            "timeout_seconds": int(self.timeout_seconds),
            "status": "failed" if self._failed else "succeeded",
            "started_at": self._started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
            "steps": self._step_reports,
            "failed": list(self._failed),
            "cleanup": {
                "status": "failed" if self._cleanup_failure_code else "succeeded",
                "failure_code": self._cleanup_failure_code,
            },
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.output_dir / f".{self.run_id}-{secrets.token_hex(4)}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                os.chmod(temporary, 0o600)
                json.dump(report, output, ensure_ascii=False, sort_keys=True, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.report_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _remaining(self) -> float:
        assert self._deadline is not None
        reserve = (
            CONTROL_RESTORE_RESERVE_SECONDS
            if self._state.get("control_restore_required") is True and self._current_step != "cleanup"
            else 0.0
        )
        remaining = self._deadline - self._clock() - reserve
        if remaining <= 0:
            raise SmokeTimeoutError("global_timeout")
        return remaining

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        query: Mapping[str, object] | None = None,
        expected_statuses: frozenset[int] = frozenset({200}),
        idempotency_key: str | None = None,
    ) -> HTTPResult:
        _require(path.startswith("/") and not path.startswith("//"), "request_path_invalid")
        suffix = f"?{urlencode(query, doseq=True)}" if query else ""
        encoded = (
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            if body is not None
            else None
        )
        headers = {"Accept": "application/json"}
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        if method in {"POST", "PATCH", "PUT", "DELETE"}:
            self._mutation_count += 1
            headers["Idempotency-Key"] = idempotency_key or (
                f"{self.run_id}:{self._current_step}:{self._mutation_count}"
            )
        request = Request(
            f"{self.base_url}{path}{suffix}",
            data=encoded,
            headers=headers,
            method=method,
        )
        timeout = max(0.001, min(10.0, self._remaining()))
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit user origin
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            status = int(exc.code)
        except TimeoutError, URLError, OSError:
            raise SmokeHTTPError("transport_failure") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SmokeHTTPError("response_too_large")
        if status not in expected_statuses:
            raise SmokeHTTPError(f"http_status_{status}")
        if not raw:
            data: object = None
        else:
            try:
                data = json.loads(raw)
            except UnicodeDecodeError, json.JSONDecodeError:
                raise SmokeHTTPError("response_json_invalid") from None
        return HTTPResult(status=status, data=data)

    def _request_bytes(
        self,
        path: str,
        *,
        expected_statuses: frozenset[int] = frozenset({200}),
    ) -> HTTPBytesResult:
        _require(path.startswith("/") and not path.startswith("//"), "request_path_invalid")
        request = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/octet-stream"},
            method="GET",
        )
        timeout = max(0.001, min(10.0, self._remaining()))
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit user origin
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            status = int(exc.code)
        except TimeoutError, URLError, OSError:
            raise SmokeHTTPError("transport_failure") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SmokeHTTPError("response_too_large")
        if status not in expected_statuses:
            raise SmokeHTTPError(f"http_status_{status}")
        return HTTPBytesResult(status=status, data=raw)

    def _restore_original_control(self) -> None:
        original = _as_dict(
            self._state.get("original_control"),
            "automation_control_restore_state_invalid",
        )
        restore_body: dict[str, object] = {
            "global_pause": original["global_pause"],
            "dry_run": original["dry_run"],
        }
        if original["global_pause"]:
            restore_body["pause_reason"] = original.get("pause_reason")
        restored = _as_dict(
            self._request(
                "PATCH",
                "/automation-control",
                body=restore_body,
            ).data,
            "automation_control_restore_invalid",
        )
        _require(
            restored.get("global_pause") is original["global_pause"] and restored.get("dry_run") is original["dry_run"],
            "automation_control_not_restored",
        )
        self._state["control_restore_required"] = False

    def _poll_job(self, job_id: str) -> dict[str, Any]:
        while True:
            response = self._request("GET", f"/jobs/{job_id}")
            job = _as_dict(response.data, "job_response_invalid")
            _require(job.get("id") in {None, job_id}, "job_identity_changed")
            status = job.get("status")
            _require(isinstance(status, str), "job_status_invalid")
            if status == "succeeded":
                _as_dict(job.get("result"), "job_result_invalid")
                return job
            if status in TERMINAL_JOB_STATUSES:
                raise SmokeInvariantError(f"job_terminal_{status}")
            _require(status in ACTIVE_JOB_STATUSES, "job_status_unknown")
            remaining = self._remaining()
            if self.poll_interval_seconds:
                self._sleeper(min(self.poll_interval_seconds, remaining))

    @staticmethod
    def _job_id(value: object, code: str) -> str:
        data = _as_dict(value, code)
        return _required_id(data.get("job_id"), code)

    def _health(self) -> StepEvidence:
        response = _as_dict(self._request("GET", "/health/live").data, "health_response_invalid")
        _require(response.get("status") == "alive", "health_not_ok")
        return StepEvidence(
            statuses={"api": "ok"},
            invariants=("api_health",),
        )

    def _configure(self) -> StepEvidence:
        original_control = _as_dict(
            self._request("GET", "/automation-control").data,
            "automation_control_invalid",
        )
        _require(
            isinstance(original_control.get("global_pause"), bool)
            and isinstance(original_control.get("dry_run"), bool),
            "automation_control_flags_invalid",
        )
        self._state["original_control"] = {
            "global_pause": original_control["global_pause"],
            "dry_run": original_control["dry_run"],
            "pause_reason": original_control.get("pause_reason"),
        }
        self._state["control_restore_required"] = True
        safe_control = _as_dict(
            self._request(
                "PATCH",
                "/automation-control",
                body={"global_pause": False, "dry_run": True},
            ).data,
            "automation_control_safety_invalid",
        )
        _require(
            safe_control.get("global_pause") is False and safe_control.get("dry_run") is True,
            "automation_control_safety_not_enabled",
        )

        brand = _as_dict(
            self._request(
                "POST",
                "/brand-profiles",
                body={
                    "name": f"{self.run_id}-brand",
                    "output_language": "fa",
                    "tone": "حرفه‌ای، دقیق و شفاف",
                    "editorial_rules": ["ادعاها باید به شواهد ثبت‌شده متکی باشند."],
                    "attribution_rules": {"preserve_sources": True},
                    "default_hashtags": [],
                    "platform_preferences": {"direction": "rtl"},
                    "is_default": False,
                },
                expected_statuses=frozenset({201}),
            ).data,
            "brand_response_invalid",
        )
        brand_id = _required_id(brand.get("id"), "brand_id_missing")
        _require(
            brand.get("name") == f"{self.run_id}-brand" and brand.get("output_language") == "fa",
            "brand_identity_invalid",
        )

        provider = _as_dict(
            self._request(
                "POST",
                "/llm-providers",
                body={
                    "name": f"{self.run_id}-provider",
                    "protocol": "fake",
                    "default_model": "fake-v1",
                    "enabled": True,
                },
                expected_statuses=frozenset({201}),
            ).data,
            "provider_response_invalid",
        )
        provider_id = _required_id(provider.get("id"), "provider_id_missing")
        _require(
            provider.get("protocol") == self.provider
            and provider.get("configured") is True
            and provider.get("generation_ready") is True
            and provider.get("research_ready") is True,
            "fake_provider_not_ready",
        )

        source_response = _as_dict(
            self._request(
                "POST",
                "/telegram/sources",
                body={
                    "name": f"{self.run_id}-source",
                    "channel_ref": "example_channel",
                    "access_mode": "public_html",
                    "language_hint": "fa",
                },
                expected_statuses=frozenset({201}),
            ).data,
            "source_response_invalid",
        )
        source_id = _required_id(source_response.get("id"), "source_id_missing")
        _require(source_response.get("access_mode") == "public_html", "source_mode_invalid")

        suffix = self.run_id.rsplit("-", 1)[1]
        bot_token = f"123456:deterministic-smoke-token-{suffix}"
        self._state["secret_canary"] = bot_token
        destination_response = _as_dict(
            self._request(
                "POST",
                "/telegram/destinations",
                body={
                    "name": f"{self.run_id}-destination",
                    "target": f"@newscraft_smoke_{suffix}",
                    "bot_token": bot_token,
                },
                expected_statuses=frozenset({202}),
            ).data,
            "destination_response_invalid",
        )
        destination = _as_dict(
            destination_response.get("destination"),
            "destination_response_invalid",
        )
        destination_id = _required_id(destination.get("id"), "destination_id_missing")
        _require(destination.get("configured") is True, "destination_must_be_configured")
        _require(destination.get("enabled") is False, "destination_must_start_disabled")
        destination_job_id = self._job_id(
            destination_response.get("job"),
            "destination_job_invalid",
        )
        destination_job = self._poll_job(destination_job_id)
        _require(destination_job.get("status") == "succeeded", "destination_check_failed")
        enabled_destination = _as_dict(
            self._request(
                "POST",
                f"/telegram/destinations/{destination_id}/enable",
                body={},
            ).data,
            "destination_enable_response_invalid",
        )
        _require(
            enabled_destination.get("configured") is True,
            "destination_configuration_lost",
        )
        _require(enabled_destination.get("enabled") is True, "destination_not_enabled")
        _require(
            enabled_destination.get("health_status") == "healthy",
            "destination_not_healthy",
        )
        _require(
            enabled_destination.get("administrator_status") == "administrator",
            "destination_not_administrator",
        )

        while True:
            options = _as_dict(
                self._request("GET", "/telegram/automations/options").data,
                "automation_options_invalid",
            )
            sources = _as_list(options.get("sources"), "automation_sources_invalid")
            destinations = _as_list(
                options.get("destinations"),
                "automation_destinations_invalid",
            )
            brands = _as_list(options.get("brand_profiles"), "brand_options_invalid")
            prompts = _as_list(
                options.get("prompt_template_versions"),
                "prompt_options_invalid",
            )
            providers = _as_list(
                options.get("ai_provider_profiles"),
                "provider_options_invalid",
            )
            source_option = next(
                (item for item in sources if isinstance(item, dict) and item.get("id") == source_id),
                None,
            )
            destination_option = next(
                (item for item in destinations if isinstance(item, dict) and item.get("id") == destination_id),
                None,
            )
            brand_option = next(
                (item for item in brands if isinstance(item, dict) and item.get("id") == brand_id),
                None,
            )
            prompt = next((item for item in prompts if isinstance(item, dict)), None)
            provider_option = next(
                (item for item in providers if isinstance(item, dict) and item.get("id") == provider_id),
                None,
            )
            source_state = source_option.get("capability_state") if source_option is not None else None
            destination_state = destination_option.get("capability_state") if destination_option is not None else None
            option_capabilities = provider_option.get("capabilities") if provider_option is not None else None
            ready = (
                brand_option is not None
                and prompt is not None
                and provider_option is not None
                and provider_option.get("configured") is True
                and isinstance(option_capabilities, dict)
                and option_capabilities.get("generation") is True
                and option_capabilities.get("research") is True
                and isinstance(source_state, dict)
                and source_state.get("status") == "available"
                and isinstance(destination_state, dict)
                and destination_state.get("status") == "available"
            )
            if ready:
                break
            remaining = self._remaining()
            if self.poll_interval_seconds:
                self._sleeper(min(self.poll_interval_seconds, remaining))
        assert prompt is not None
        prompt_id = _required_id(prompt.get("id"), "prompt_id_missing")

        route_response = _as_dict(
            self._request(
                "POST",
                "/telegram/automations",
                body={
                    "name": f"{self.run_id}-route",
                    "source_id": source_id,
                    "destination_id": destination_id,
                    "brand_profile_id": brand_id,
                    "prompt_template_version_id": prompt_id,
                    "prompt_policy": "pinned",
                    "ai_provider_profile_id": provider_id,
                    "access_mode": "public_html",
                    "research_mode": "off",
                    "content_filters": {"model": "fake-v1"},
                    "media_policy": "preserve",
                    "attribution_policy": "preserve",
                    "publishing_policy": "review_required",
                    "poll_interval_seconds": 300,
                },
                expected_statuses=frozenset({201}),
            ).data,
            "route_response_invalid",
        )
        route_id = _required_id(route_response.get("id"), "route_id_missing")

        activation = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/activate",
                body={},
                expected_statuses=frozenset({202}),
            ).data,
            "route_activation_invalid",
        )
        initial_route = _as_dict(activation.get("route"), "route_activation_invalid")
        initial_cursor = _as_dict(
            initial_route.get("cursor_state"),
            "route_initial_cursor_invalid",
        )
        _require(initial_cursor.get("status") == "initializing", "route_not_initializing")
        _require(
            initial_cursor.get("activation_message_id") is None and initial_cursor.get("last_message_id") is None,
            "new_post_only_cursor_not_empty",
        )
        activation_job_id = self._job_id(activation.get("job"), "activation_job_invalid")
        self._poll_job(activation_job_id)
        ready_route = _as_dict(
            self._request("GET", f"/telegram/automations/{route_id}").data,
            "ready_route_invalid",
        )
        ready_cursor = _as_dict(ready_route.get("cursor_state"), "ready_cursor_invalid")
        _require(ready_route.get("enabled") is True, "route_not_enabled")
        _require(ready_cursor.get("status") == "ready", "route_not_ready")
        _require(
            ready_cursor.get("activation_message_id") == 44 and ready_cursor.get("last_message_id") == 44,
            "new_post_only_activation_head_invalid",
        )

        invalid_backfill = self._request(
            "POST",
            f"/telegram/automations/{route_id}/backfill",
            body={"count": 101},
            expected_statuses=frozenset({422}),
        )
        _require(invalid_backfill.status == 422, "backfill_bound_not_enforced")

        self._state.update(
            {
                "source_id": source_id,
                "destination_id": destination_id,
                "brand_id": brand_id,
                "prompt_id": prompt_id,
                "provider_id": provider_id,
                "route_id": route_id,
            }
        )
        return StepEvidence(
            ids={
                "source_id": source_id,
                "destination_id": destination_id,
                "destination_check_job_id": destination_job_id,
                "route_id": route_id,
                "activation_job_id": activation_job_id,
            },
            statuses={"route": "ready", "destination": "healthy"},
            invariants=(
                "synthetic_encrypted_destination_credential",
                "deterministic_destination_health_check",
                "unique_persian_brand_and_fake_provider",
                "whole_run_dry_run_safety",
                "new_post_only_route_activation",
                "bounded_backfill_validation",
            ),
        )

    def _manual_intake(self) -> StepEvidence:
        accepted = _as_dict(
            self._request(
                "POST",
                "/stories/manual",
                body={
                    "kind": "text",
                    "title": f"{self.run_id} گزارش آزمایشی",
                    "text": ("این متن مستند آزمایشی برای اجرای کامل و قطعی گردش محلی نیوزکرفت ثبت شده است."),
                    "source_label": f"{self.run_id}-operator",
                },
                expected_statuses=frozenset({202}),
            ).data,
            "manual_intake_response_invalid",
        )
        job_id = _required_id(accepted.get("job_id"), "manual_intake_job_missing")
        job = self._poll_job(job_id)
        result = _as_dict(job.get("result"), "manual_intake_result_invalid")
        story_id = _required_id(result.get("story_id"), "manual_intake_story_missing")
        self._state["story_id"] = story_id
        return StepEvidence(
            ids={"job_id": job_id, "story_id": story_id},
            statuses={"job": "succeeded"},
            invariants=("manual_text_intake",),
        )

    def _collect(self) -> StepEvidence:
        story_id = str(self._state["story_id"])
        story = _as_dict(
            self._request("GET", f"/stories/{story_id}").data,
            "story_response_invalid",
        )
        _require(story.get("id") == story_id, "story_identity_changed")
        _require(
            isinstance(story.get("evidence_count"), int) and story["evidence_count"] >= 1,
            "story_evidence_count_invalid",
        )
        evidence = _as_list(
            self._request("GET", f"/stories/{story_id}/evidence").data,
            "story_evidence_invalid",
        )
        _require(bool(evidence), "story_evidence_missing")
        evidence_ids: list[str] = []
        for item in evidence:
            row = _as_dict(item, "story_evidence_invalid")
            evidence_ids.append(_required_id(row.get("id"), "evidence_id_missing"))
            _required_hash(row.get("content_sha256"), "evidence_hash_invalid")
            _require(bool(row.get("content_text")), "evidence_text_missing")
        self._state["evidence_ids"] = evidence_ids
        return StepEvidence(
            ids={"story_id": story_id, "evidence_ids": evidence_ids},
            statuses={"collection": "materialized"},
            invariants=("immutable_evidence_materialized",),
        )

    def _research(self) -> StepEvidence:
        story_id = str(self._state["story_id"])
        provider_id = str(self._state["provider_id"])
        disposition = _as_dict(
            self._request(
                "POST",
                f"/stories/{story_id}/research-runs",
                body={
                    "mode": "manual",
                    "depth": "standard",
                    "provider_profile_id": provider_id,
                    "query_hint": "deterministic acceptance evidence",
                },
                expected_statuses=frozenset({202}),
            ).data,
            "research_disposition_invalid",
        )
        _require(disposition.get("disposition") == "enqueued", "research_not_enqueued")
        run_id = _required_id(disposition.get("run_id"), "research_run_id_missing")
        job_id = _required_id(disposition.get("job_id"), "research_job_id_missing")
        self._poll_job(job_id)
        run = _as_dict(
            self._request("GET", f"/research-runs/{run_id}").data,
            "research_run_invalid",
        )
        _require(
            run.get("id") == run_id
            and run.get("story_id") == story_id
            and run.get("status") == "succeeded"
            and run.get("job_status") == "succeeded",
            "research_run_not_succeeded",
        )
        revision_id = _required_id(
            run.get("result_revision_id"),
            "research_revision_id_missing",
        )
        revisions = _as_list(
            self._request("GET", f"/stories/{story_id}/revisions").data,
            "story_revisions_invalid",
        )
        revision = next(
            (item for item in revisions if isinstance(item, dict) and item.get("id") == revision_id),
            None,
        )
        _require(revision is not None, "research_revision_missing")
        citations = _as_list(revision.get("citations"), "research_citations_invalid")
        _require(bool(citations), "research_citations_missing")
        for item in citations:
            citation = _as_dict(item, "research_citation_invalid")
            _required_id(
                citation.get("evidence_snapshot_id"),
                "research_citation_snapshot_missing",
            )
            _required_hash(
                citation.get("excerpt_sha256"),
                "research_citation_hash_invalid",
            )
            _require(bool(citation.get("locator")), "research_citation_locator_missing")
        self._state.update({"research_run_id": run_id, "research_revision_id": revision_id})
        return StepEvidence(
            ids={"run_id": run_id, "job_id": job_id, "revision_id": revision_id},
            statuses={"research": "succeeded"},
            invariants=("research_citations",),
        )

    def _generate_four_platforms(self) -> StepEvidence:
        story_id = str(self._state["story_id"])
        accepted = _as_dict(
            self._request(
                "POST",
                f"/stories/{story_id}/content-packs",
                body={
                    "brand_profile_id": self._state["brand_id"],
                    "platforms": list(PLATFORMS),
                    "generation_provider_profile_id": self._state["provider_id"],
                    "research_mode": "off",
                    "research_run_id": self._state["research_run_id"],
                },
                expected_statuses=frozenset({202}),
            ).data,
            "generation_response_invalid",
        )
        job_id = _required_id(accepted.get("job_id"), "generation_job_id_missing")
        root = self._poll_job(job_id)
        root_result = _as_dict(root.get("result"), "generation_root_result_invalid")
        child_job_id = _required_id(
            root_result.get("continuation_job_id"),
            "generation_continuation_missing",
        )
        child = self._poll_job(child_job_id)
        child_result = _as_dict(child.get("result"), "generation_child_result_invalid")
        pack_id = _required_id(child_result.get("content_pack_id"), "content_pack_id_missing")
        pack = _as_dict(
            self._request("GET", f"/content-packs/{pack_id}").data,
            "content_pack_invalid",
        )
        _require(pack.get("id") == pack_id, "content_pack_identity_changed")
        _require(
            pack.get("status") in {"draft", "ready", "needs_review"},
            "content_pack_status_invalid",
        )
        variants = _as_list(pack.get("variants"), "platform_variants_invalid")
        platforms = [item.get("platform") if isinstance(item, dict) else None for item in variants]
        _require(platforms == list(PLATFORMS), "four_platform_set_invalid")
        by_platform: dict[str, dict[str, Any]] = {}
        for item in variants:
            variant = _as_dict(item, "platform_variant_invalid")
            platform = str(variant["platform"])
            revision = _as_dict(
                variant.get("current_revision"),
                "platform_current_revision_missing",
            )
            content = _as_dict(revision.get("content"), "platform_payload_invalid")
            _required_id(variant.get("id"), "platform_variant_id_missing")
            _required_id(revision.get("id"), "platform_revision_id_missing")
            _required_hash(revision.get("content_hash"), "platform_content_hash_invalid")
            _require(
                revision.get("approval_state") == "pending_review",
                "platform_review_state_invalid",
            )
            if platform == "telegram":
                _require(
                    bool(content.get("body")) and content.get("parse_mode") == "HTML",
                    "telegram_payload_invalid",
                )
            elif platform == "instagram":
                _require(
                    bool(content.get("caption"))
                    and isinstance(content.get("carousel"), list)
                    and bool(content.get("citations")),
                    "instagram_payload_invalid",
                )
            elif platform == "x":
                posts = _as_list(content.get("posts"), "x_payload_invalid")
                _require(
                    bool(posts)
                    and all(
                        isinstance(post, dict) and bool(post.get("text")) and bool(post.get("citations"))
                        for post in posts
                    ),
                    "x_payload_invalid",
                )
            elif platform == "blog":
                _require(
                    bool(content.get("title"))
                    and bool(content.get("body_markdown"))
                    and bool(content.get("citations")),
                    "blog_payload_invalid",
                )
            by_platform[platform] = {"variant": variant, "revision": revision}
        self._state.update({"pack_id": pack_id, "platforms": by_platform})
        return StepEvidence(
            ids={
                "root_job_id": job_id,
                "continuation_job_id": child_job_id,
                "content_pack_id": pack_id,
                "revision_ids": [str(by_platform[platform]["revision"]["id"]) for platform in PLATFORMS],
            },
            statuses={"content_pack": str(pack["status"])},
            invariants=("four_platform_payloads",),
        )

    def _approve(self, revision_id: str, content_hash: str) -> dict[str, Any]:
        approved = _as_dict(
            self._request(
                "POST",
                f"/platform-variant-revisions/{revision_id}/approve",
                body={
                    "expected_content_hash": content_hash,
                    "note": f"{self.run_id} exact approval",
                },
            ).data,
            "approval_response_invalid",
        )
        _require(
            approved.get("id") == revision_id
            and approved.get("content_hash") == content_hash
            and approved.get("approval_state") == "approved",
            "exact_approval_failed",
        )
        return approved

    def _edit_and_approve(self) -> StepEvidence:
        platforms: dict[str, dict[str, Any]] = self._state["platforms"]
        telegram = platforms["telegram"]
        base = telegram["revision"]
        base_id = _required_id(base.get("id"), "telegram_base_revision_missing")
        base_hash = _required_hash(base.get("content_hash"), "telegram_base_hash_missing")
        self._approve(base_id, base_hash)
        base_content = _as_dict(base.get("content"), "telegram_base_content_invalid")
        variant_id = _required_id(
            telegram["variant"].get("id"),
            "telegram_variant_id_missing",
        )
        edited = _as_dict(
            self._request(
                "POST",
                f"/platform-variants/{variant_id}/revisions",
                body={
                    "base_revision_id": base_id,
                    "base_content_hash": base_hash,
                    "content": {
                        "body": f"{base_content['body']}\n\n{self.run_id}",
                        "parse_mode": base_content.get("parse_mode", "HTML"),
                        "buttons": base_content.get("buttons", []),
                    },
                    "media_asset_ids": base_content.get("media_asset_ids", []),
                    "edit_note": f"{self.run_id} deterministic edit",
                },
                expected_statuses=frozenset({201}),
            ).data,
            "telegram_edit_response_invalid",
        )
        edited_id = _required_id(edited.get("id"), "edited_revision_id_missing")
        edited_hash = _required_hash(edited.get("content_hash"), "edited_revision_hash_missing")
        _require(
            edited.get("parent_revision_id") == base_id and edited.get("approval_state") == "pending_review",
            "edit_did_not_invalidate_approval",
        )

        wrong_hash = "0" * 64 if edited_hash != "0" * 64 else "1" * 64
        rejected = self._request(
            "POST",
            f"/platform-variant-revisions/{edited_id}/approve",
            body={"expected_content_hash": wrong_hash, "note": None},
            expected_statuses=frozenset({409}),
        )
        _require(rejected.status == 409, "stale_approval_hash_not_rejected")
        self._approve(edited_id, edited_hash)

        approved_revisions: dict[str, dict[str, str]] = {"telegram": {"id": edited_id, "hash": edited_hash}}
        for platform in PLATFORMS[1:]:
            revision = platforms[platform]["revision"]
            revision_id = _required_id(revision.get("id"), "revision_id_missing")
            content_hash = _required_hash(
                revision.get("content_hash"),
                "revision_hash_missing",
            )
            self._approve(revision_id, content_hash)
            approved_revisions[platform] = {"id": revision_id, "hash": content_hash}
        self._state["approved_revisions"] = approved_revisions
        return StepEvidence(
            ids={
                "base_revision_id": base_id,
                "edited_revision_id": edited_id,
                "approved_revision_ids": [approved_revisions[platform]["id"] for platform in PLATFORMS],
            },
            statuses={"edited_revision": "approved"},
            invariants=("edit_invalidates_approval", "exact_reapproval"),
        )

    def _telegram_dry_run(self) -> StepEvidence:
        route_id = str(self._state["route_id"])
        replay_key = f"{self.run_id}:telegram-dry-run:44"
        first = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/dry-run",
                body={"source_message_id": 44},
                expected_statuses=frozenset({202}),
                idempotency_key=replay_key,
            ).data,
            "telegram_dry_run_invalid",
        )
        first_job = _as_dict(first.get("job"), "telegram_dry_run_job_invalid")
        job_id = _required_id(first_job.get("job_id"), "telegram_dry_run_job_missing")
        job = self._poll_job(job_id)
        result = _as_dict(job.get("result"), "telegram_dry_run_result_invalid")
        dispatch_id = _required_id(result.get("dispatch_id"), "telegram_dispatch_id_missing")
        dispatches = _as_list(
            self._request("GET", f"/telegram/automations/{route_id}/dispatches").data,
            "telegram_dispatches_invalid",
        )
        dispatch = next(
            (item for item in dispatches if isinstance(item, dict) and item.get("id") == dispatch_id),
            None,
        )
        _require(dispatch is not None, "telegram_dry_run_dispatch_missing")
        _require(
            dispatch.get("dispatch_kind") == "dry_run"
            and dispatch.get("source_message_ids") == [42, 43, 44]
            and dispatch.get("publish_job_id") is None,
            "telegram_album_not_preserved",
        )
        _require(
            dispatch.get("status") in {"captured", "researching", "generating", "needs_review"},
            "telegram_dry_run_status_invalid",
        )

        replay = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/dry-run",
                body={"source_message_id": 44},
                expected_statuses=frozenset({202}),
                idempotency_key=replay_key,
            ).data,
            "telegram_dry_run_replay_invalid",
        )
        replay_job = _as_dict(replay.get("job"), "telegram_dry_run_replay_job_invalid")
        _require(
            replay_job.get("job_id") == job_id and replay_job.get("deduplicated") is True,
            "telegram_dry_run_not_deduplicated",
        )
        replay_dispatches = _as_list(
            self._request("GET", f"/telegram/automations/{route_id}/dispatches").data,
            "telegram_replay_dispatches_invalid",
        )
        matching = [
            item
            for item in replay_dispatches
            if isinstance(item, dict)
            and item.get("dispatch_kind") == "dry_run"
            and item.get("source_message_ids") == [42, 43, 44]
        ]
        _require(
            len(matching) == 1 and matching[0].get("publish_job_id") is None,
            "duplicate_publish_prevention_failed",
        )
        return StepEvidence(
            ids={"job_id": job_id, "dispatch_id": dispatch_id},
            statuses={"dispatch": str(dispatch["status"])},
            invariants=("album_preservation", "duplicate_publish_prevention"),
        )

    def _export(self) -> StepEvidence:
        pack_id = str(self._state["pack_id"])
        approved: dict[str, dict[str, str]] = self._state["approved_revisions"]
        revision_ids = [approved[platform]["id"] for platform in PLATFORMS]
        accepted = _as_dict(
            self._request(
                "POST",
                f"/content-packs/{pack_id}/exports",
                body={
                    "content_pack_id": pack_id,
                    "revision_ids": revision_ids,
                    "formats": ["json", "markdown", "html", "zip"],
                    "include_media": False,
                },
                expected_statuses=frozenset({202}),
            ).data,
            "export_response_invalid",
        )
        job_id = _required_id(accepted.get("job_id"), "export_job_id_missing")
        self._poll_job(job_id)
        export = _as_dict(
            self._request("GET", f"/exports/{job_id}").data,
            "export_artifact_response_invalid",
        )
        _require(
            export.get("export_id") == job_id and export.get("status") == "succeeded",
            "export_not_succeeded",
        )
        artifact = _as_dict(export.get("artifact"), "export_artifact_missing")
        _require(
            artifact.get("export_id") == job_id
            and artifact.get("content_pack_id") == pack_id
            and artifact.get("state") == "complete",
            "export_artifact_identity_invalid",
        )
        manifest = _as_dict(artifact.get("manifest"), "export_manifest_missing")
        _require(
            manifest.get("schema_version") == "newscraft-export-v1" and manifest.get("content_pack_id") == pack_id,
            "export_manifest_identity_invalid",
        )
        canonical_manifest = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        expected_manifest_hash = hashlib.sha256(canonical_manifest).hexdigest()
        _require(
            artifact.get("manifest_sha256") == expected_manifest_hash,
            "export_manifest_checksum_invalid",
        )
        variants = _as_list(manifest.get("variants"), "export_manifest_variants_invalid")
        actual_revisions = {
            str(item.get("revision_id"))
            for item in variants
            if isinstance(item, dict) and item.get("approval_state") == "approved"
        }
        _require(actual_revisions == set(revision_ids), "export_revision_set_invalid")
        files = _as_list(manifest.get("files"), "export_manifest_files_invalid")
        _require(bool(files), "export_manifest_files_missing")
        names: list[str] = []
        for item in files:
            file = _as_dict(item, "export_manifest_file_invalid")
            name = file.get("file_name")
            _require(isinstance(name, str) and bool(name), "export_file_name_invalid")
            names.append(str(name))
            _required_hash(file.get("sha256"), "export_file_checksum_invalid")
            _require(
                isinstance(file.get("byte_length"), int) and file["byte_length"] >= 0,
                "export_file_length_invalid",
            )
        _require(len(names) == len(set(names)), "export_file_names_not_unique")
        archive_file = artifact.get("archive_file")
        _require(
            isinstance(archive_file, str) and bool(archive_file),
            "export_archive_missing",
        )
        archive_hash = _required_hash(
            artifact.get("archive_sha256"),
            "export_archive_checksum_invalid",
        )
        manifest_file = artifact.get("manifest_file")
        _require(
            isinstance(manifest_file, str) and bool(manifest_file),
            "export_manifest_file_missing",
        )
        expected_downloads: dict[str, tuple[str, int | None]] = {
            str(manifest_file): (expected_manifest_hash, len(canonical_manifest)),
            str(archive_file): (archive_hash, None),
        }
        for item in files:
            file = _as_dict(item, "export_manifest_file_invalid")
            expected_downloads[str(file["file_name"])] = (
                str(file["sha256"]),
                int(file["byte_length"]),
            )
        downloads = _as_list(export.get("downloads"), "export_downloads_invalid")
        _require(len(downloads) == len(expected_downloads), "export_download_count_invalid")
        downloaded: dict[str, bytes] = {}
        prefix = f"/exports/{job_id}/download/"
        for path in downloads:
            _require(
                isinstance(path, str) and path.startswith(prefix),
                "export_download_path_invalid",
            )
            file_name = str(path).removeprefix(prefix)
            _require(
                file_name in expected_downloads and file_name not in downloaded,
                "export_download_set_invalid",
            )
            content = self._request_bytes(str(path)).data
            expected_hash, expected_length = expected_downloads[file_name]
            _require(
                hashlib.sha256(content).hexdigest() == expected_hash,
                "export_download_checksum_invalid",
            )
            if expected_length is not None:
                _require(len(content) == expected_length, "export_download_length_invalid")
            downloaded[file_name] = content
        _require(set(downloaded) == set(expected_downloads), "export_download_set_invalid")
        _require(
            downloaded[str(manifest_file)] == canonical_manifest,
            "export_manifest_download_not_canonical",
        )
        self._state["export_id"] = job_id
        return StepEvidence(
            ids={"job_id": job_id, "content_pack_id": pack_id},
            statuses={"export": "succeeded"},
            invariants=(
                "export_manifest_checksums",
                "export_download_bytes_verified",
            ),
        )

    def _manual_plan(self) -> StepEvidence:
        approved: dict[str, dict[str, str]] = self._state["approved_revisions"]
        revision_id = approved["instagram"]["id"]
        scheduled = self._now().astimezone(UTC) + timedelta(days=1)
        scheduled_text = scheduled.isoformat().replace("+00:00", "Z")
        plan = _as_dict(
            self._request(
                "POST",
                "/manual-publication-plans",
                body={
                    "revision_id": revision_id,
                    "scheduled_for": scheduled_text,
                    "display_timezone": "Asia/Tehran",
                },
                expected_statuses=frozenset({201}),
            ).data,
            "manual_plan_response_invalid",
        )
        plan_id = _required_id(plan.get("id"), "manual_plan_id_missing")
        _require(
            plan.get("platform_variant_revision_id") == revision_id
            and plan.get("platform") == "instagram"
            and plan.get("status") == "planned"
            and plan.get("display_timezone") == "Asia/Tehran",
            "manual_plan_identity_invalid",
        )
        _require(
            _parse_time(plan.get("scheduled_for"), "manual_plan_schedule_invalid") == scheduled,
            "manual_plan_schedule_changed",
        )
        checklist = _as_dict(
            plan.get("checklist_state"),
            "manual_plan_checklist_invalid",
        )
        _require(
            bool(checklist)
            and all(isinstance(key, str) and key for key in checklist)
            and all(value is False for value in checklist.values()),
            "manual_plan_checklist_invalid",
        )
        readback = _as_dict(
            self._request(
                "GET",
                f"/platform-variant-revisions/{revision_id}/manual-publication-plan",
            ).data,
            "manual_plan_readback_invalid",
        )
        _require(
            readback.get("id") == plan_id
            and readback.get("platform_variant_revision_id") == revision_id
            and _parse_time(
                readback.get("scheduled_for"),
                "manual_plan_readback_schedule_invalid",
            )
            == scheduled,
            "manual_plan_readback_changed",
        )
        completed = _as_dict(
            self._request(
                "PATCH",
                f"/manual-publication-plans/{plan_id}/checklist",
                body={"checklist_state": {key: True for key in checklist}},
            ).data,
            "manual_plan_checklist_response_invalid",
        )
        completed_checklist = _as_dict(
            completed.get("checklist_state"),
            "manual_plan_checklist_response_invalid",
        )
        _require(
            completed.get("id") == plan_id
            and completed.get("status") == "ready"
            and set(completed_checklist) == set(checklist)
            and all(value is True for value in completed_checklist.values()),
            "manual_plan_checklist_not_completed",
        )
        return StepEvidence(
            ids={"plan_id": plan_id, "revision_id": revision_id},
            statuses={"manual_plan": "ready"},
            invariants=(
                "manual_publication_plan",
                "manual_checklist_completed",
            ),
        )

    def _pause_and_resume(self) -> StepEvidence:
        route_id = str(self._state["route_id"])
        _require(self._remaining() >= 75, "insufficient_time_for_pause_test")
        paused = _as_dict(
            self._request(
                "PATCH",
                "/automation-control",
                body={
                    "global_pause": True,
                    "dry_run": True,
                    "pause_reason": f"{self.run_id} acceptance",
                },
            ).data,
            "global_pause_response_invalid",
        )
        _require(paused.get("global_pause") is True, "global_pause_not_enabled")
        resumed_route = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/resume",
                body={},
            ).data,
            "route_resume_invalid",
        )
        _require(resumed_route.get("paused_at") is None, "route_not_resumed")
        override = _as_dict(
            self._request("GET", "/automation-control").data,
            "global_pause_override_invalid",
        )
        _require(
            override.get("global_pause") is True and resumed_route.get("paused_at") is None,
            "global_pause_did_not_override_route",
        )
        accepted = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/backfill",
                body={"count": 1},
                expected_statuses=frozenset({202}),
            ).data,
            "paused_backfill_response_invalid",
        )
        backfill_job_id = self._job_id(
            accepted.get("job"),
            "paused_backfill_job_invalid",
        )
        held_job = _as_dict(
            self._request("GET", f"/jobs/{backfill_job_id}").data,
            "paused_backfill_job_invalid",
        )
        _require(
            held_job.get("id") == backfill_job_id
            and held_job.get("job_type") == "telegram.route.backfill"
            and held_job.get("status") == "queued"
            and held_job.get("pause_sensitive") is True
            and held_job.get("started_at") is None,
            "pause_sensitive_job_not_held",
        )
        paused_route = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/pause",
                body={},
            ).data,
            "route_pause_invalid",
        )
        _require(paused_route.get("paused_at") is not None, "route_not_paused")
        resumed_again = _as_dict(
            self._request(
                "POST",
                f"/telegram/automations/{route_id}/resume",
                body={},
            ).data,
            "route_second_resume_invalid",
        )
        _require(resumed_again.get("paused_at") is None, "route_second_resume_failed")
        resumed_control = _as_dict(
            self._request(
                "PATCH",
                "/automation-control",
                body={"global_pause": False, "dry_run": True},
            ).data,
            "global_resume_response_invalid",
        )
        _require(
            resumed_control.get("global_pause") is False and resumed_control.get("dry_run") is True,
            "global_resume_failed",
        )
        completed_job = self._poll_job(backfill_job_id)
        _require(completed_job.get("status") == "succeeded", "paused_backfill_not_resumed")
        return StepEvidence(
            ids={"route_id": route_id, "backfill_job_id": backfill_job_id},
            statuses={
                "global_pause": "resumed",
                "route": "resumed",
                "backfill": "succeeded",
            },
            invariants=(
                "global_pause_override",
                "route_pause_and_resume",
                "pause_sensitive_job_held",
                "pause_sensitive_job_resumed",
            ),
        )

    def _history(self) -> StepEvidence:
        story_id = str(self._state["story_id"])
        story_history = _as_dict(
            self._request(
                "GET",
                "/operations/history",
                query={"subject_type": "story", "subject_id": story_id, "limit": 50},
            ).data,
            "operations_history_invalid",
        )
        route_id = str(self._state["route_id"])
        route_history = _as_dict(
            self._request(
                "GET",
                "/operations/history",
                query={
                    "subject_type": "automation_route",
                    "subject_id": route_id,
                    "limit": 50,
                },
            ).data,
            "route_history_invalid",
        )
        pause_history = _as_dict(
            self._request(
                "GET",
                "/operations/history",
                query={"category": "pause", "limit": 50},
            ).data,
            "pause_history_invalid",
        )
        pages = (story_history, route_history, pause_history)
        counts: list[int] = []
        for page in pages:
            items = _as_list(page.get("items"), "operations_history_items_invalid")
            _require(bool(items), "operations_history_empty")
            _require(
                all(
                    isinstance(item, dict)
                    and bool(item.get("id"))
                    and bool(item.get("category"))
                    and bool(item.get("status"))
                    for item in items
                ),
                "operations_history_entry_invalid",
            )
            counts.append(len(items))
        pause_items = _as_list(pause_history.get("items"), "pause_history_items_invalid")
        _require(
            all(isinstance(item, dict) and item.get("category") == "pause" for item in pause_items),
            "pause_history_category_invalid",
        )
        serialized = json.dumps(pages, ensure_ascii=False, sort_keys=True)
        _require(
            str(self._state["secret_canary"]) not in serialized,
            "history_secret_canary_leaked",
        )
        return StepEvidence(
            ids={
                "story_id": story_id,
                "route_id": route_id,
                "entry_count": sum(counts),
            },
            statuses={"history": "available"},
            invariants=(
                "subject_history",
                "route_history",
                "pause_history",
                "history_secret_absence",
            ),
        )

    def _diagnostics(self) -> StepEvidence:
        diagnostics = _as_dict(
            self._request("GET", "/operations/diagnostics").data,
            "diagnostics_response_invalid",
        )
        generated_at = _parse_time(
            diagnostics.get("generated_at"),
            "diagnostics_generated_at_invalid",
        )
        components = _as_dict(
            diagnostics.get("components"),
            "diagnostics_components_invalid",
        )
        _require(
            EXPECTED_RUNTIME_COMPONENTS.issubset(components),
            "diagnostics_components_missing",
        )
        component_statuses: dict[str, str] = {}
        for name in sorted(EXPECTED_RUNTIME_COMPONENTS):
            component = _as_dict(components[name], "diagnostics_component_invalid")
            status = component.get("status")
            _require(
                status in {"healthy", "degraded", "down", "unknown"},
                "component_status_invalid",
            )
            observed_at = _parse_time(
                component.get("observed_at"),
                "component_observed_at_invalid",
            )
            _require(observed_at <= generated_at, "component_observation_from_future")
            component_statuses[name] = str(status)
        queue_counts = _as_dict(
            diagnostics.get("queue_counts"),
            "diagnostics_queue_counts_invalid",
        )
        _require(
            EXPECTED_QUEUE_STATUSES.issubset(queue_counts)
            and all(
                isinstance(queue_counts[status], int) and queue_counts[status] >= 0
                for status in EXPECTED_QUEUE_STATUSES
            ),
            "diagnostics_queue_counts_invalid",
        )
        _require(
            diagnostics.get("global_paused") is False and diagnostics.get("dry_run") is True,
            "diagnostics_control_state_changed",
        )
        return StepEvidence(
            ids={"queue_total": sum(int(value) for value in queue_counts.values())},
            statuses=component_statuses,
            invariants=("runtime_diagnostics", "queue_truth", "control_truth"),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--provider", required=True, choices=("fake",))
    parser.add_argument("--telegram-mode", required=True, choices=("dry-run",))
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    poll_interval_seconds: float = 0.25,
) -> int:
    args = _parser().parse_args(argv)
    driver = SmokeDriver(
        base_url=args.base_url,
        output_dir=args.output_dir,
        provider=args.provider,
        telegram_mode=args.telegram_mode,
        poll_interval_seconds=poll_interval_seconds,
    )
    result = driver.run()
    print(result.report_path)
    if result.failed:
        print(f"smoke failed at step: {result.failed[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
