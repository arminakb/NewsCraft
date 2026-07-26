from __future__ import annotations

from types import UnionType
from typing import Any, Union, get_args, get_origin
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

from app.generation.default_prompts import manual_generation_provider_schema
from app.generation.multiplatform import payload_claims
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramSlide,
    InstagramVariantPayload,
    MediaAssignment,
    Platform,
    PlatformPayload,
    XPost,
    XVariantPayload,
)
from app.generation.platform_validation import (
    ValidationIssue,
    validate_platform_payload,
)
from app.generation.telegram_schema import TelegramRewriteOutput
from app.research.citations import validate_citations
from app.stories.evidence import EvidenceRecord


def _strict_or_loose_payload[T: BaseModel](
    payload_type: type[T],
    raw: dict[str, Any],
) -> T:
    try:
        return payload_type.model_validate(raw)
    except ValidationError:
        schema = manual_generation_provider_schema(payload_type)
        errors = list(
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).iter_errors(to_jsonable_python(raw))
        )
        if errors:
            raise ValueError("manual platform output failed structural validation") from None
        return _construct_manual_payload(payload_type, raw)


def _manual_output_with_ordinary_issues(
    platform: Platform,
    raw: dict[str, Any],
) -> tuple[Any, list[ValidationIssue]]:
    payload: PlatformPayload
    if platform == "instagram":
        payload = _strict_or_loose_payload(InstagramVariantPayload, raw)
    elif platform == "x":
        payload = _strict_or_loose_payload(XVariantPayload, raw)
    elif platform == "blog":
        payload = _strict_or_loose_payload(BlogVariantPayload, raw)
    else:
        raise ValueError("manual platform output requires a manual platform")
    validator: Any
    if isinstance(payload, InstagramVariantPayload | XVariantPayload):
        validator = payload.reject_citation_userinfo
    else:
        validator = payload.reject_url_userinfo
    validator()
    return payload, validate_platform_payload(platform, payload)


def validate_provider_output(
    raw: dict[str, Any],
    *,
    platform: Platform,
    evidence: dict[UUID, EvidenceRecord],
) -> Any:
    if platform == "telegram":
        return TelegramRewriteOutput.model_validate(raw)
    authored, _issues = _manual_output_with_ordinary_issues(platform, raw)
    validate_citations(payload_claims(platform, authored), evidence)
    return authored


_LOOSE_MANUAL_MODELS = {
    InstagramVariantPayload,
    InstagramSlide,
    XVariantPayload,
    XPost,
    BlogVariantPayload,
    MediaAssignment,
}


def _construct_manual_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    if origin is list:
        item_type = get_args(annotation)[0]
        return [_construct_manual_value(item_type, item) for item in value]
    if origin in {Union, UnionType}:
        if value is None:
            return None
        target = next(item for item in get_args(annotation) if item is not type(None))
        return _construct_manual_value(target, value)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in _LOOSE_MANUAL_MODELS:
            return _construct_manual_payload(annotation, value)
        return annotation.model_validate(value)
    return TypeAdapter(annotation).validate_python(value)


def _construct_manual_payload[T: BaseModel](
    model_type: type[T],
    raw: dict[str, Any],
) -> T:
    values = {
        name: _construct_manual_value(model_type.model_fields[name].annotation, value) for name, value in raw.items()
    }
    return model_type.model_construct(**values)
