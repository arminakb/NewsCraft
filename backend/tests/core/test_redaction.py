from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl

from app.core.logging import configure_logging
from app.core.redaction import redact_request_target, redact_secrets, redact_string, redact_url


class DeliveryMode(StrEnum):
    SAFE = "safe"


class Priority(IntEnum):
    NORMAL = 2


class RedactionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str
    created_at: datetime
    endpoint: HttpUrl


@dataclass
class RedactionDataclass:
    password: str
    identifier: UUID


class LeakyUnknown:
    def __str__(self) -> str:
        return "password=unknown-secret"


class CountingIterable:
    def __init__(self) -> None:
        self.yield_count = 0

    def __iter__(self) -> Iterator[int]:
        value = 0
        while True:
            self.yield_count += 1
            yield value
            value += 1


def test_redact_string_applies_literals_auth_tokens_and_urls() -> None:
    value = (
        "explicit-canary Bearer auth-canary "
        "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi "
        "https://user:pass@example.com/path?api_key=query-canary&safe=yes"
    )

    redacted = redact_string(value, secrets=("explicit-canary",))

    assert "explicit-canary" not in redacted
    assert "auth-canary" not in redacted
    assert "123456789:" not in redacted
    assert "user:pass" not in redacted
    assert "query-canary" not in redacted
    assert "safe=yes" in redacted
    assert "[REDACTED]" in redacted
    assert redact_url("https://user:pass@example.com/a?token=one&q=ok") == (
        "https://example.com/a?token=%5BREDACTED%5D&q=ok"
    )


def test_redact_request_target_preserves_path_and_safe_query_diagnostics() -> None:
    target = (
        "/health/live?token=token-canary&key=key-canary&session_id=session-canary"
        "&credential_ref=credential-canary&safe=yes&max_output_tokens=10"
    )

    redacted = redact_request_target(target)

    assert redacted.startswith("/health/live?")
    assert "safe=yes" in redacted
    assert "max_output_tokens=10" in redacted
    assert all(
        canary not in redacted for canary in ("token-canary", "key-canary", "session-canary", "credential-canary")
    )
    assert redacted.count("%5BREDACTED%5D") == 4


def test_redact_string_handles_quoted_pairs_fragments_and_delimited_pairs() -> None:
    value = "provider error {'api_key': 'repr-canary'} {\"database_url\": \"json-canary\"} safe=x,api_key=comma-canary"

    redacted = redact_string(value)
    redacted_url = redact_string("https://user:pass@example.com/x?safe=yes#token=fragment-canary")

    assert all(canary not in redacted for canary in ("repr-canary", "json-canary", "comma-canary"))
    assert "fragment-canary" not in redacted_url
    assert "user:pass" not in redacted_url
    assert "safe=yes" in redacted_url
    assert "[REDACTED]" in redacted
    assert redact_string(redacted) == redacted
    assert redacted_url == "https://example.com/x?safe=yes#token=[REDACTED]"
    assert redact_string(redacted_url) == redacted_url
    assert redact_string("token=") == "token=[REDACTED]"


def test_redact_string_fail_closed_for_nested_values_under_secret_keys() -> None:
    values = (
        "provider {'api_key': {'nested': 'python-nested-canary'}}",
        'provider {"database_url": {"nested": "json-nested-canary"}}',
        "provider {'private_key': ['list-nested-canary', {'more': 'data'}]}",
        "provider {'api_key': {'nested': 'unterminated-canary'",
    )

    for value in values:
        redacted = redact_string(value)
        assert "canary" not in redacted
        assert "[REDACTED]" in redacted
        assert redact_string(redacted) == redacted

    safe_metrics = "{'token_usage': {'input_tokens': 10, 'output_tokens': 4}}"
    assert redact_string(safe_metrics) == safe_metrics


def test_redact_string_handles_inline_composites_and_secret_colon_fields() -> None:
    value = (
        "api_key={'nested':'inline-composite-canary'} "
        "X-Api-Key: header-api-canary\n"
        "api_key: field-api-canary\n"
        "X-Auth-Token: header-token-canary\n"
        "Password: password-canary"
    )

    redacted = redact_string(value)

    assert "canary" not in redacted
    assert redacted.count("[REDACTED]") == 5
    assert redact_string(redacted) == redacted
    safe_metrics = "token_usage: {'input_tokens': 10, 'output_tokens': 4}"
    assert redact_string(safe_metrics) == safe_metrics


def test_redact_string_drops_over_cap_secret_scalars_and_redacts_escaped_bodies() -> None:
    over_cap = "provider {'api_key': '" + ("x" * 32_769) + "scalar-tail-canary'} visible-tail"
    escaped = 'body="{\\"api_key\\":\\"escaped-body-canary\\"}"'

    capped = redact_string(over_cap)
    redacted_escaped = redact_string(escaped)

    assert "scalar-tail-canary" not in capped
    assert "visible-tail" not in capped
    assert capped.endswith("'api_key': [REDACTED]")
    assert "escaped-body-canary" not in redacted_escaped
    assert redacted_escaped == "body=[REDACTED]"
    assert redact_string(capped) == capped
    assert redact_string(redacted_escaped) == redacted_escaped


def test_recursive_redaction_handles_cycles_depth_keys_and_safe_metrics() -> None:
    value: dict[str, object] = {
        "Authorization": "Bearer abc",
        "nested": [
            {
                "bot_token": "secret",
                "private_key": "private-canary",
                "payload": b"secret-bytes",
            }
        ],
        "input_tokens": 10,
        "output_tokens": 4,
        "token_usage": {"total": 14},
        "tokenizer_name": "safe-tokenizer",
        "session_count": 2,
    }
    value["cycle"] = value
    deeply_nested: object = "leaf"
    for _ in range(22):
        deeply_nested = {"nested": deeply_nested}
    value["deep"] = deeply_nested

    redacted = redact_secrets(value)
    serialized = json.dumps(redacted)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"] == [
        {
            "bot_token": "[REDACTED]",
            "private_key": "[REDACTED]",
            "payload": "[BYTES:12]",
        }
    ]
    assert redacted["cycle"] == "[CYCLE]"
    assert "[MAX_DEPTH]" in serialized
    assert redacted["input_tokens"] == 10
    assert redacted["output_tokens"] == 4
    assert redacted["token_usage"] == {"total": 14}
    assert redacted["tokenizer_name"] == "[REDACTED]"
    assert redacted["session_count"] == 2


def test_token_metric_exemptions_require_numeric_contract_values() -> None:
    unsafe = {
        "input_tokens": "input-metric-canary",
        "max_input_tokens": "max-input-metric-canary",
        "max_output_tokens": "max-output-metric-canary",
        "output_tokens": "output-metric-canary",
        "session_count": "session-metric-canary",
        "token_usage": {"access_token": "usage-metric-canary"},
        "tokenizer_name": "tokenizer-metric-canary",
    }

    assert redact_secrets(unsafe) == {key: "[REDACTED]" for key in unsafe}
    assert redact_string("max_input_tokens=max-input-text-canary") == ("max_input_tokens=[REDACTED]")
    assert redact_string("token_usage: {'access_token': 'usage-text-canary'}") == ("token_usage:[REDACTED]")
    assert redact_url("https://example.com/?max_output_tokens=url-metric-canary") == (
        "https://example.com/?max_output_tokens=%5BREDACTED%5D"
    )


def test_opaque_and_byte_mapping_keys_fail_closed() -> None:
    redacted = redact_secrets(
        {
            b"api_key": "byte-key-canary",
            ("password",): "tuple-key-canary",
            "x" * 1_000: "oversized-key-canary",
        }
    )

    serialized = json.dumps(redacted)
    assert "byte-key-canary" not in serialized
    assert "tuple-key-canary" not in serialized
    assert "oversized-key-canary" not in serialized
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["[tuple]"] == "[REDACTED]"
    assert redacted["[str]"] == "[REDACTED]"


def test_recursive_redaction_serializes_models_dataclasses_and_safe_scalars() -> None:
    timestamp = datetime(2026, 7, 13, 8, 30, tzinfo=UTC)
    identifier = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    value = {
        "model": RedactionModel(
            api_key="model-secret",
            created_at=timestamp,
            endpoint="https://user:pass@example.com/path?api_key=query-secret&safe=yes",
        ),
        "dataclass": RedactionDataclass(password="data-secret", identifier=identifier),
        "decimal": Decimal("12.50"),
        "mode": DeliveryMode.SAFE,
        "priority": Priority.NORMAL,
        "unknown": LeakyUnknown(),
    }

    redacted = redact_secrets(value)

    assert redacted == {
        "model": {
            "api_key": "[REDACTED]",
            "created_at": "2026-07-13T08:30:00Z",
            "endpoint": "https://example.com/path?api_key=%5BREDACTED%5D&safe=yes",
        },
        "dataclass": {
            "password": "[REDACTED]",
            "identifier": str(identifier),
        },
        "decimal": "12.50",
        "mode": "safe",
        "priority": 2,
        "unknown": "[LeakyUnknown]",
    }
    assert type(redacted["priority"]) is int
    assert "unknown-secret" not in json.dumps(redacted)


def test_recursive_redaction_caps_mappings_and_lazy_iterables_without_materializing() -> None:
    source = CountingIterable()

    redacted_mapping = redact_secrets({f"key-{index}": index for index in range(600)})
    redacted_sequence = redact_secrets(source)

    assert len(redacted_mapping) == 500
    assert redacted_sequence == list(range(1_000))
    assert source.yield_count == 1_000


def test_recursive_redaction_removes_explicit_secrets_from_mapping_key_names() -> None:
    source = {"prefix-explicit-canary-suffix": "visible"}

    redacted = redact_secrets(source, secrets=("explicit-canary",))

    assert redacted == {"prefix-[REDACTED]-suffix": "visible"}
    assert "explicit-canary" not in repr(redacted)


def test_configure_logging_sanitizes_messages_args_exceptions_stack_and_extras() -> None:
    root = logging.getLogger()
    logger = logging.getLogger("tests.security.redaction")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s extras=%(api_key)s metadata=%(metadata)s"))
    original_handlers = list(root.handlers)
    original_level = root.level
    original_propagate = logger.propagate
    original_logger_level = logger.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = True
    logger.setLevel(logging.INFO)
    try:
        configure_logging()
        configure_logging()
        try:
            raise RuntimeError("provider error {'api_key': {'nested': 'exception-canary'}}")
        except RuntimeError:
            logger.exception(
                "Bearer message-canary",
                extra={
                    "api_key": "extra-canary",
                    "metadata": {"access_token": "nested-canary", "safe": "yes"},
                },
                stack_info=True,
            )
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        logger.propagate = original_propagate
        logger.setLevel(original_logger_level)

    output = stream.getvalue()
    assert "message-canary" not in output
    assert "exception-canary" not in output
    assert "extra-canary" not in output
    assert "nested-canary" not in output
    assert "[REDACTED]" in output
    assert "metadata={'access_token': '[REDACTED]', 'safe': 'yes'}" in output


def test_configured_logging_does_not_trust_a_caller_supplied_redaction_marker() -> None:
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    original_handlers = list(root.handlers)
    original_level = root.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    try:
        configure_logging()
        root.info(
            "token=marker-bypass-canary",
            extra={"_newscraft_redacted": True},
        )
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)

    output = stream.getvalue()
    assert "marker-bypass-canary" not in output
    assert "[REDACTED]" in output


def test_configured_logging_replaces_extras_beyond_the_mapping_cap() -> None:
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s overflow=%(overflow)s"))
    original_handlers = list(root.handlers)
    original_level = root.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    extras: dict[str, object] = {f"safe_{index}": index for index in range(500)}
    extras["overflow"] = "token=overflow-canary"
    try:
        configure_logging()
        root.info("safe message", extra=extras)
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)

    output = stream.getvalue()
    assert "overflow-canary" not in output
    assert "overflow=[TRUNCATED]" in output


def test_configured_logging_covers_existing_and_future_loggers_with_late_handlers() -> None:
    original_logger_class = logging.getLoggerClass()
    existing_name = "tests.security.existing-late-handler"
    future_name = "tests.security.future-late-handler"
    logging.Logger.manager.loggerDict.pop(existing_name, None)
    logging.Logger.manager.loggerDict.pop(future_name, None)
    logging.setLoggerClass(logging.Logger)
    existing = logging.getLogger(existing_name)
    existing_stream = io.StringIO()
    future_stream = io.StringIO()
    try:
        configure_logging()
        existing.handlers = [logging.StreamHandler(existing_stream)]
        existing.setLevel(logging.INFO)
        existing.propagate = False
        future = logging.getLogger(future_name)
        future.handlers = [logging.StreamHandler(future_stream)]
        future.setLevel(logging.INFO)
        future.propagate = False

        existing.info("api_key=existing-late-canary")
        future.info("token=future-late-canary")
    finally:
        logging.Logger.manager.loggerDict.pop(existing_name, None)
        logging.Logger.manager.loggerDict.pop(future_name, None)
        logging.setLoggerClass(original_logger_class)

    output = existing_stream.getvalue() + future_stream.getvalue()
    assert "existing-late-canary" not in output
    assert "future-late-canary" not in output
    assert output.count("[REDACTED]") == 2


def test_configured_logging_redacts_composite_and_escaped_string_arguments() -> None:
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    original_handlers = list(root.handlers)
    original_level = root.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    try:
        configure_logging()
        root.error(
            "provider composite=%s escaped=%s",
            "api_key={'nested':'log-composite-canary'}",
            'body="{\\"api_key\\":\\"log-escaped-canary\\"}"',
        )
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)

    output = stream.getvalue()
    assert "log-composite-canary" not in output
    assert "log-escaped-canary" not in output
    assert output.count("[REDACTED]") >= 2


def test_worker_main_activates_logging_before_cli_execution(monkeypatch) -> None:
    from app.jobs import worker as worker_module

    observed: list[str] = []

    async def fake_run_worker(capabilities: tuple[str, ...]) -> None:
        assert capabilities == ("publishing",)
        observed.append("run")

    monkeypatch.setattr(
        worker_module,
        "configure_logging",
        lambda: observed.append("configure"),
        raising=False,
    )
    monkeypatch.setattr(
        worker_module,
        "parse_capabilities",
        lambda: observed.append("parse") or ("publishing",),
    )
    monkeypatch.setattr(worker_module, "run_worker", fake_run_worker)

    worker_module.main()

    assert observed == ["configure", "parse", "run"]


def test_scheduler_main_activates_logging_before_cli_execution(monkeypatch) -> None:
    from app.jobs import scheduler as scheduler_module

    observed: list[str] = []

    async def fake_run_scheduler() -> None:
        observed.append("run")

    monkeypatch.setattr(
        scheduler_module,
        "configure_logging",
        lambda: observed.append("configure"),
        raising=False,
    )
    monkeypatch.setattr(scheduler_module, "run_scheduler", fake_run_scheduler)

    scheduler_module.main()

    assert observed == ["configure", "run"]
