"""Test-only access to generation operation boundaries.

Production callers register the concrete operation modules directly. Tests keep
this small import surface so focused lifecycle fixtures can select an operation
without restoring the removed production compatibility facade.
"""

from app.generation.canonical_generation import build_canonical_generation_handler
from app.generation.generation_helpers import (
    _require_exact_active_canonical_prompt,
    _require_exact_regeneration_dispatch,
    artifact_requires_review,
    platform_limits_for,
    platform_stage_input,
    render_prompt_messages,
    require_exact_active_prompt,
    require_prompt_integrity,
)
from app.generation.package_evidence import locked_story_evidence
from app.generation.package_generation import build_pack_generation_handler
from app.generation.platform_media import trusted_story_media, validate_payload_media_assignments
from app.generation.platform_output import _manual_output_with_ordinary_issues
from app.generation.provider_execution import invoke
from app.generation.provider_results import normalize_provider_usage
from app.generation.revision_fence import clear_regeneration_fence, require_revision_write_allowed
from app.generation.variant_regeneration import build_regenerate_handler

__all__ = [
    "artifact_requires_review",
    "invoke",
    "locked_story_evidence",
    "_manual_output_with_ordinary_issues",
    "platform_stage_input",
    "_require_exact_active_canonical_prompt",
    "require_exact_active_prompt",
    "_require_exact_regeneration_dispatch",
    "trusted_story_media",
    "build_canonical_generation_handler",
    "build_pack_generation_handler",
    "build_regenerate_handler",
    "clear_regeneration_fence",
    "platform_limits_for",
    "normalize_provider_usage",
    "render_prompt_messages",
    "require_prompt_integrity",
    "require_revision_write_allowed",
    "validate_payload_media_assignments",
]
