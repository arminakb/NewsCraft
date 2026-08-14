from __future__ import annotations

import ast
import dataclasses
import json
import math
import re
import sys
import threading
from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from itertools import islice
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel

_REDACTED = "[REDACTED]"
_CYCLE = "[CYCLE]"
_MAX_DEPTH = "[MAX_DEPTH]"
_MAX_MAPPING_ITEMS = 500
_MAX_MAPPING_KEY_CHARS = 512
_MAX_SEQUENCE_ITEMS = 1_000
_MAX_STRUCTURED_VALUE_CHARS = 32_768
_MAX_STRUCTURED_VALUE_DEPTH = 20
_MAX_EMBEDDED_REDACTION_DEPTH = 4

_SAFE_NUMERIC_KEYS = {
    "input_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "max_tokens",
    "output_tokens",
    "session_count",
    "token_count",
    "tokens_per_second",
}
_SAFE_NUMERIC_CONTAINER_KEYS = {"token_usage"}

SECRET_KEY_PATTERN = re.compile(
    r"(?i)(authorization|cookie|token|secret|password|api[_-]?key|private[_-]?key|session|credential|database[_-]?url)"
)
BEARER_PATTERN = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
TELEGRAM_TOKEN_PATTERN = re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")
_URL_VALUE_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_UNICODE_KEY_ESCAPE_PATTERN = re.compile(r"\\u([0-9a-fA-F]{4})")
_HEX_KEY_ESCAPE_PATTERN = re.compile(r"\\x([0-9a-fA-F]{2})")
_NUMERIC_TEXT_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_STRUCTURED_CLOSERS = {"{": "}", "[": "]", "(": ")"}

_DEGRADATION_LABEL_PATTERN = re.compile(r"[^A-Za-z0-9_.]+")
_DEGRADATION_LOCK = threading.Lock()
_DEGRADATION_COUNTS: dict[tuple[str, str], int] = {}


def record_sanitizer_degradation(scope: str, exc: BaseException) -> str:
    """Count one fail-closed sanitizer degradation and name each new kind once.

    Redaction is deliberately fail-closed: when inspecting a value raises, the
    caller substitutes a type-name placeholder rather than risk emitting the
    value. That is correct, and it is also indistinguishable from a value that
    was simply unrenderable — so a systematic failure (a redaction bug turning
    every log line into a placeholder) leaves no trace at all. This counter is
    that trace.

    Only the scope and the exception's class name are recorded; the value being
    sanitized never reaches this function, so nothing here can leak. The stderr
    line fires only on the first occurrence of each (scope, class) pair, so a
    hot loop degrades quietly after announcing itself once, and it is written
    directly rather than logged because the log formatters are themselves one
    of the callers.

    Returns the sanitized class label so callers can embed it in their own
    diagnostic output.
    """

    label = _DEGRADATION_LABEL_PATTERN.sub("_", type(exc).__name__)[:64] or "Exception"
    key = (scope, label)
    with _DEGRADATION_LOCK:
        count = _DEGRADATION_COUNTS.get(key, 0) + 1
        _DEGRADATION_COUNTS[key] = count
    if count == 1:
        try:
            sys.stderr.write(f"[REDACTION_DEGRADED] scope={scope} error={label}\n")
        except Exception:
            # A closed or hostile stderr must not turn an already-degraded
            # sanitizer into a raised exception inside a log formatter. The
            # count above is kept regardless, so the signal is not lost.
            pass
    return label


def sanitizer_degradation_counts() -> dict[tuple[str, str], int]:
    """Snapshot the fail-closed degradation counts by (scope, exception class)."""

    with _DEGRADATION_LOCK:
        return dict(_DEGRADATION_COUNTS)


def reset_sanitizer_degradation_counts() -> None:
    """Clear the degradation counts. Intended for tests and process bootstrap."""

    with _DEGRADATION_LOCK:
        _DEGRADATION_COUNTS.clear()


def _normalized_key(key: object) -> str:
    return str(key).casefold().replace("-", "_").replace(" ", "_")


def _secret_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return bool(SECRET_KEY_PATTERN.search(normalized))


def _safe_numeric_value(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Decimal):
        return value.is_finite()
    return False


def _safe_numeric_mapping(value: object) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    try:
        for key, nested in value.items():
            key_name, inspectable = _safe_mapping_key(key)
            if not inspectable:
                return False
            normalized = _normalized_key(key_name)
            if not _safe_numeric_value(nested):
                return False
            if _secret_key(key_name) and normalized not in _SAFE_NUMERIC_KEYS:
                return False
    except Exception as exc:
        record_sanitizer_degradation("numeric_mapping_classification", exc)
        return False
    return True


def _safe_serialized_numeric_mapping(value: str) -> bool:
    candidate = value.strip()
    if not candidate.startswith("{") or not candidate.endswith("}") or len(candidate) > _MAX_STRUCTURED_VALUE_CHARS:
        return False
    parsed: object
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError, UnicodeError:
        try:
            parsed = ast.literal_eval(candidate)
        except MemoryError, RecursionError, SyntaxError, ValueError:
            return False
    return _safe_numeric_mapping(parsed)


def _safe_secret_value(key: object, value: object, *, serialized: bool = False) -> bool:
    normalized = _normalized_key(key)
    if normalized in _SAFE_NUMERIC_KEYS:
        if serialized:
            return isinstance(value, str) and bool(_NUMERIC_TEXT_PATTERN.fullmatch(value.strip()))
        return _safe_numeric_value(value)
    if normalized in _SAFE_NUMERIC_CONTAINER_KEYS:
        if serialized:
            return isinstance(value, str) and _safe_serialized_numeric_mapping(value)
        return _safe_numeric_mapping(value)
    return False


def _redact_key_value(key: object, value: object, *, serialized: bool = False) -> bool:
    return _secret_key(key) and not _safe_secret_value(key, value, serialized=serialized)


def _sensitive_query_value(key: object, value: object) -> bool:
    normalized = _normalized_key(key)
    return "key" in normalized.split("_") or _redact_key_value(key, value, serialized=True)


def _safe_mapping_key(key: object) -> tuple[str, bool]:
    if isinstance(key, Enum):
        return _safe_mapping_key(key.value)
    if isinstance(key, bytes):
        try:
            name = key.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return "[bytes]", False
    elif key is None or isinstance(key, (str, bool, int, float, Decimal, UUID)):
        name = str(key)
    else:
        return f"[{type(key).__name__}]", False
    if len(name) > _MAX_MAPPING_KEY_CHARS:
        return f"[{type(key).__name__}]", False
    return name, True


def redact_url(url: str) -> str:
    """Remove user information and secret query values from an HTTP(S) URL."""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return _REDACTED
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return url

    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        return _REDACTED
    netloc = f"{hostname}:{port}" if port is not None else hostname
    query = [
        (
            key,
            _REDACTED if _sensitive_query_value(key, value) else _redact_recognizable_values(value),
        )
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            netloc,
            _redact_recognizable_values(parsed.path),
            urlencode(query),
            _redact_recognizable_values(parsed.fragment),
        )
    )


def redact_request_target(target: str) -> str:
    """Redact a relative HTTP request target while preserving useful routing data."""

    try:
        parsed = urlsplit(target)
    except UnicodeError, ValueError:
        return _REDACTED
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.casefold() in {"http", "https"} and parsed.hostname:
            return redact_url(target)
        return _REDACTED
    try:
        query = [
            (
                _redact_recognizable_values(key),
                _REDACTED if _sensitive_query_value(key, value) else _redact_recognizable_values(value),
            )
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    except UnicodeError, ValueError:
        return _REDACTED
    return urlunsplit(
        (
            "",
            "",
            _redact_recognizable_values(parsed.path),
            urlencode(query),
            _redact_recognizable_values(parsed.fragment),
        )
    )


def _literal_secrets(secrets: Collection[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {secret for secret in secrets if isinstance(secret, str) and secret},
            key=len,
            reverse=True,
        )
    )


def _quoted_value_end(value: str, start: int, *, limit: int) -> int | None:
    quote = value[start]
    index = start + 1
    while index < limit:
        current = value[index]
        if current == "\\":
            index += 2
            continue
        if current == quote:
            return index + 1
        index += 1
    return None


def _structured_value_end(value: str, start: int, *, bare_delimiters: str = ",}])\r\n") -> int | None:
    if start >= len(value):
        return len(value)
    current = value[start]
    limit = min(len(value), start + _MAX_STRUCTURED_VALUE_CHARS)
    if current in {'"', "'"}:
        return _quoted_value_end(value, start, limit=limit)
    if current not in _STRUCTURED_CLOSERS:
        return _bare_value_end(value, start, limit=limit, delimiters=bare_delimiters)

    return _container_value_end(value, start, limit=limit)


def _bare_value_end(value: str, start: int, *, limit: int, delimiters: str) -> int | None:
    index = start
    while index < limit and value[index] not in delimiters:
        index += 1
    if index == limit and limit < len(value):
        return None
    return index


def _container_value_end(value: str, start: int, *, limit: int) -> int | None:
    current = value[start]
    expected_closers = [_STRUCTURED_CLOSERS[current]]
    index = start + 1
    while index < limit:
        current = value[index]
        if current in {'"', "'"}:
            quoted_end = _quoted_value_end(value, index, limit=limit)
            if quoted_end is None:
                return None
            index = quoted_end
            continue
        if current in _STRUCTURED_CLOSERS:
            if len(expected_closers) >= _MAX_STRUCTURED_VALUE_DEPTH:
                return None
            expected_closers.append(_STRUCTURED_CLOSERS[current])
        elif current in _STRUCTURED_CLOSERS.values():
            if current != expected_closers[-1]:
                return None
            expected_closers.pop()
            if not expected_closers:
                return index + 1
        index += 1
    return None


def _decode_structured_key(value: str) -> str:
    decoded = _UNICODE_KEY_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), value)
    decoded = _HEX_KEY_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), decoded)
    return re.sub(r"\\([\\\"'/])", r"\1", decoded)


def _field_name_character(value: str) -> bool:
    return value.isascii() and (value.isalnum() or value in "._-")


def _field_name_end(value: str, start: int) -> int:
    index = start
    limit = min(len(value), start + 128)
    while index < limit and _field_name_character(value[index]):
        index += 1
    return index


def _decode_quoted_body(value: str) -> str:
    quote = value[0]
    result: list[str] = []
    index = 1
    limit = len(value) - 1
    while index < limit:
        current = value[index]
        if (
            current == "\\"
            and index + 1 < limit
            and value[index + 1]
            in {
                quote,
                "\\",
                '"',
                "'",
            }
        ):
            result.append(value[index + 1])
            index += 2
            continue
        result.append(current)
        index += 1
    return "".join(result)


def _quoted_body_requires_redaction(value: str, *, embedded_depth: int) -> bool:
    decoded = _decode_quoted_body(value)
    if embedded_depth >= _MAX_EMBEDDED_REDACTION_DEPTH:
        return bool(SECRET_KEY_PATTERN.search(decoded))
    return _redact_recognizable_values(decoded, embedded_depth=embedded_depth + 1) != decoded


def _structured_pair_bounds(value: str, index: int) -> tuple[int, int] | None:
    key_end = _quoted_value_end(
        value,
        index,
        limit=min(len(value), index + _MAX_STRUCTURED_VALUE_CHARS),
    )
    if key_end is None:
        return None
    colon = key_end
    while colon < len(value) and value[colon].isspace():
        colon += 1
    if colon >= len(value) or value[colon] != ":":
        return None
    value_start = colon + 1
    while value_start < len(value) and value[value_start].isspace():
        value_start += 1
    return key_end, value_start


def _redacted_structured_pair(raw_key: str, quote: str) -> str:
    return f"{quote}{raw_key}{quote}: {_REDACTED}"


def _redact_secret_structured_value(
    value: str,
    *,
    index: int,
    value_start: int,
    raw_key: str,
    decoded_key: str,
) -> tuple[str | None, int]:
    value_end = _structured_value_end(value, value_start, bare_delimiters=",}])\r\n \t")
    if value_end is not None and _safe_secret_value(
        decoded_key,
        value[value_start:value_end],
        serialized=True,
    ):
        return None, value_end
    replacement = _redacted_structured_pair(raw_key, value[index])
    return replacement, value_end if value_end is not None else len(value)


def _redact_embedded_structured_value(
    value: str,
    *,
    index: int,
    value_start: int,
    raw_key: str,
    embedded_depth: int,
) -> tuple[str | None, int | None]:
    if value_start >= len(value) or value[value_start] not in {'"', "'"}:
        return None, None
    value_end = _structured_value_end(value, value_start)
    if value_end is None:
        return _redacted_structured_pair(raw_key, value[index]), len(value)
    if _quoted_body_requires_redaction(value[value_start:value_end], embedded_depth=embedded_depth):
        return _redacted_structured_pair(raw_key, value[index]), value_end
    return None, None


def _redact_structured_pairs(value: str, *, embedded_depth: int) -> str:
    result: list[str] = []
    cursor = 0
    index = 0
    while index < len(value):
        if value[index] not in {'"', "'"}:
            index += 1
            continue
        bounds = _structured_pair_bounds(value, index)
        if bounds is None:
            index += 1
            continue
        key_end, value_start = bounds
        raw_key = value[index + 1 : key_end - 1]
        decoded_key = _decode_structured_key(raw_key)
        if _secret_key(decoded_key):
            replacement, value_end = _redact_secret_structured_value(
                value,
                index=index,
                value_start=value_start,
                raw_key=raw_key,
                decoded_key=decoded_key,
            )
            if replacement is None:
                index = value_end
                continue
            result.append(value[cursor:index])
            result.append(replacement)
            if value_end == len(value):
                return "".join(result)
            cursor = value_end
            index = value_end
            continue
        replacement, embedded_end = _redact_embedded_structured_value(
            value,
            index=index,
            value_start=value_start,
            raw_key=raw_key,
            embedded_depth=embedded_depth,
        )
        if replacement is not None and embedded_end is not None:
            result.append(value[cursor:index])
            result.append(replacement)
            if embedded_end == len(value):
                return "".join(result)
            cursor = embedded_end
            index = embedded_end
            continue
        index = key_end
    result.append(value[cursor:])
    return "".join(result)


def _unquoted_field_bounds(value: str, index: int, separator: str) -> tuple[int, int] | None:
    if not _field_name_character(value[index]) or (index > 0 and _field_name_character(value[index - 1])):
        return None
    key_end = _field_name_end(value, index)
    delimiter = key_end
    while delimiter < len(value) and value[delimiter].isspace():
        delimiter += 1
    if delimiter >= len(value) or value[delimiter] != separator:
        return key_end, -1
    value_start = delimiter + 1
    while value_start < len(value) and value[value_start].isspace():
        value_start += 1
    return key_end, value_start


def _embedded_unquoted_replacement(
    value: str,
    *,
    key: str,
    value_start: int,
    embedded_depth: int,
) -> tuple[str | None, int | None]:
    if value_start >= len(value) or value[value_start] not in {'"', "'"}:
        return None, None
    value_end = _structured_value_end(value, value_start)
    if value_end is None or _quoted_body_requires_redaction(
        value[value_start:value_end],
        embedded_depth=embedded_depth,
    ):
        return f"{key}={_REDACTED}", value_end if value_end is not None else len(value)
    return None, None


def _redact_unquoted_fields(value: str, *, separator: str, embedded_depth: int) -> str:
    result: list[str] = []
    cursor = 0
    index = 0
    while index < len(value):
        bounds = _unquoted_field_bounds(value, index, separator)
        if bounds is None:
            index += 1
            continue
        key_end, value_start = bounds
        if value_start < 0:
            index = max(key_end, index + 1)
            continue
        key = value[index:key_end]
        secret_key = _secret_key(key)
        if not secret_key and separator == "=" and value_start < len(value):
            replacement, value_end = _embedded_unquoted_replacement(
                value,
                key=key,
                value_start=value_start,
                embedded_depth=embedded_depth,
            )
            if replacement is not None and value_end is not None:
                result.append(value[cursor:index])
                result.append(replacement)
                if value_end == len(value):
                    return "".join(result)
                cursor = value_end
                index = value_end
                continue
            index = key_end
            continue
        if not secret_key:
            index = key_end
            continue

        value_end = _structured_value_end(
            value,
            value_start,
            bare_delimiters=(",}])\r\n&;# \t" if separator == "=" else ",}])\r\n"),
        )
        if value_end is not None and _safe_secret_value(
            key,
            value[value_start:value_end],
            serialized=True,
        ):
            index = value_end
            continue
        result.append(value[cursor:index])
        result.append(f"{key}{separator}{_REDACTED}")
        if value_end is None:
            return "".join(result)
        cursor = value_end
        index = value_end
    result.append(value[cursor:])
    return "".join(result)


def _redact_recognizable_values(value: str, *, embedded_depth: int = 0) -> str:
    result = BEARER_PATTERN.sub(_REDACTED, value)
    result = TELEGRAM_TOKEN_PATTERN.sub(_REDACTED, result)
    result = _redact_structured_pairs(result, embedded_depth=embedded_depth)
    result = _redact_unquoted_fields(result, separator=":", embedded_depth=embedded_depth)
    return _redact_unquoted_fields(result, separator="=", embedded_depth=embedded_depth)


def redact_string(value: str, *, secrets: Collection[str] = ()) -> str:
    """Return *value* with literal and recognizable credentials removed."""

    result = value
    for secret in _literal_secrets(secrets):
        result = result.replace(secret, _REDACTED)
    result = _redact_recognizable_values(result)

    try:
        parsed = urlsplit(result)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.scheme.casefold() in {"http", "https"}:
        return redact_url(result)
    return _URL_VALUE_PATTERN.sub(lambda match: redact_url(match.group(0)), result)


def redact_secrets(
    value: object,
    *,
    secrets: Collection[str] = (),
    seen: set[int] | None = None,
    depth: int = 0,
) -> object:
    """Return a bounded, recursively sanitized copy without mutating *value*."""

    scalar = _redact_scalar(value, secrets=secrets, seen=seen, depth=depth)
    if scalar is not _NOT_SCALAR:
        return scalar

    active = seen if seen is not None else set()
    identity = id(value)
    if identity in active:
        return _CYCLE
    active.add(identity)
    try:
        return _redact_complex(value, secrets=secrets, active=active, depth=depth)
    finally:
        active.remove(identity)


_NOT_SCALAR = object()


def _redact_scalar(
    value: object,
    *,
    secrets: Collection[str],
    seen: set[int] | None,
    depth: int,
) -> object:
    if depth > 20:
        return _MAX_DEPTH
    if value is None:
        return value
    if isinstance(value, Enum):
        return redact_secrets(value.value, secrets=secrets, seen=seen, depth=depth)
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[BYTES:{len(value)}]"
    if isinstance(value, str):
        return redact_string(value, secrets=secrets)
    return _NOT_SCALAR


def _convert_complex(value: object) -> tuple[object, str | None]:
    if isinstance(value, BaseModel):
        try:
            return value.model_dump(mode="json"), None
        except Exception as exc:
            record_sanitizer_degradation("pydantic_model_dump", exc)
            return value, f"[{type(value).__name__}]"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}, None
        except Exception as exc:
            record_sanitizer_degradation("dataclass_fields", exc)
            return value, f"[{type(value).__name__}]"
    return value, None


def _redact_mapping(
    value: object,
    converted: Mapping[object, object],
    *,
    secrets: Collection[str],
    active: set[int],
    depth: int,
) -> object:
    result: dict[str, object] = {}
    try:
        entries = islice(converted.items(), _MAX_MAPPING_ITEMS)
        for key, nested in entries:
            original_name, inspectable = _safe_mapping_key(key)
            name = redact_string(original_name, secrets=secrets)
            result[name] = (
                _REDACTED
                if not inspectable or _redact_key_value(original_name, nested)
                else redact_secrets(nested, secrets=secrets, seen=active, depth=depth + 1)
            )
    except Exception as exc:
        record_sanitizer_degradation("mapping_traversal", exc)
        return f"[{type(value).__name__}]"
    return result


def _redact_iterable(
    value: object,
    converted: Iterable[object],
    *,
    secrets: Collection[str],
    active: set[int],
    depth: int,
) -> object:
    result: list[object] = []
    try:
        for nested in islice(iter(converted), _MAX_SEQUENCE_ITEMS):
            result.append(redact_secrets(nested, secrets=secrets, seen=active, depth=depth + 1))
    except Exception as exc:
        record_sanitizer_degradation("sequence_traversal", exc)
        return f"[{type(value).__name__}]"
    return result


def _redact_complex(
    value: object,
    *,
    secrets: Collection[str],
    active: set[int],
    depth: int,
) -> object:
    converted, failure = _convert_complex(value)
    if failure is not None:
        return failure
    if isinstance(converted, Mapping):
        return _redact_mapping(value, converted, secrets=secrets, active=active, depth=depth)
    if isinstance(converted, Iterable):
        return _redact_iterable(value, converted, secrets=secrets, active=active, depth=depth)
    return f"[{type(value).__name__}]"
