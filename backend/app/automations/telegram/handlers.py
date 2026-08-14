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
)
from app.automations.telegram.process_support import (
    dispatch_media,
    enqueue_telegram_publish_intent,
    media_decision,
    require_automation_variant_write_allowed,
    resolve_process_prompt,
)
from app.automations.telegram.route_operations import build_telegram_route_handlers

__all__ = [
    "ProcessDispatchPayload",
    "dispatch_media",
    "media_decision",
    "require_automation_variant_write_allowed",
    "resolve_process_prompt",
    "build_evidence_map",
    "build_telegram_process_handler",
    "build_telegram_route_handlers",
    "enqueue_telegram_publish_intent",
    "generation_input_hash",
    "sha256_canonical",
    "validate_evidence_snapshot",
]
