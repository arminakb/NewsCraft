from __future__ import annotations

import io
import logging

from app.core.logging import configure_logging
from app.jobs.events import redact_event_data
from app.operations.diagnostics import _safe_text


def test_configured_logging_redacts_message_args_exceptions_urls_and_extras():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_factory = logging.getLogRecordFactory()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(context)s"))
    context = {
        "cookie": "cookie-canary",
        "url": "https://user:pass@example.com/fail?api_key=query-canary&safe=yes",
    }

    try:
        root.handlers[:] = [handler]
        root.setLevel(logging.INFO)
        configure_logging()
        configure_logging()

        try:
            raise RuntimeError("token=exception-canary")
        except RuntimeError:
            root.error(
                "provider failed: %s",
                "Bearer argument-canary",
                extra={"context": context},
                exc_info=True,
            )
    finally:
        root.handlers[:] = original_handlers
        root.setLevel(original_level)
        logging.setLogRecordFactory(original_factory)

    emitted = stream.getvalue()
    assert all(
        canary not in emitted
        for canary in (
            "argument-canary",
            "cookie-canary",
            "query-canary",
            "exception-canary",
            "user:pass",
        )
    )
    assert "[REDACTED]" in emitted
    assert "safe=yes" in emitted
    assert context["cookie"] == "cookie-canary"


def test_workflow_event_boundary_redacts_before_serialization_without_mutation():
    source = {
        "Authorization": "Bearer event-canary",
        "nested": {
            "database_url": "postgresql://operator:database-canary@example.com/newscraft",
            "detail": "token=detail-canary",
        },
    }

    sanitized = redact_event_data(source)

    serialized = repr(sanitized)
    assert "event-canary" not in serialized
    assert "database-canary" not in serialized
    assert "detail-canary" not in serialized
    assert serialized.count("[REDACTED]") >= 3
    assert source["Authorization"] == "Bearer event-canary"
    assert source["nested"]["detail"] == "token=detail-canary"


def test_diagnostics_redacts_secrets_constructed_across_display_components():
    rendered = _safe_text(
        "Source ",
        "Authorization",
        ": ",
        "diagnostics-cross-boundary-canary",
    )

    assert "diagnostics-cross-boundary-canary" not in rendered
    assert "[REDACTED]" in rendered
