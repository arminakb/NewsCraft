"""Stable Telegram job-handler imports.

Route capture and dispatch processing live in separate operation modules so the
job registry remains small and callers keep one maintenance-safe import path.
"""

from app.automations.telegram.handler_contracts import (
    ProcessDispatchPayload,
    build_evidence_map,
    generation_input_hash,
    sha256_canonical,
    validate_evidence_snapshot,
)
from app.automations.telegram.process_operations import (
    build_telegram_process_handler,
    process_route_dispatch,
)
from app.automations.telegram.process_support import (
    _dispatch_media,
    _media_decision,
    _require_automation_variant_write_allowed,
    _resolve_process_prompt,
    enqueue_telegram_publish_intent,
)
from app.automations.telegram.route_operations import build_telegram_route_handlers

__all__ = [
    "ProcessDispatchPayload",
    "_dispatch_media",
    "_media_decision",
    "_require_automation_variant_write_allowed",
    "_resolve_process_prompt",
    "build_evidence_map",
    "build_telegram_process_handler",
    "build_telegram_route_handlers",
    "enqueue_telegram_publish_intent",
    "generation_input_hash",
    "process_route_dispatch",
    "sha256_canonical",
    "validate_evidence_snapshot",
]
