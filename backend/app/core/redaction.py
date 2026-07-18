from __future__ import annotations

import ast
import dataclasses
import json
import math
import re
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
    except Exception:
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
        index = start
        while index < limit and value[index] not in bare_delimiters:
            index += 1
        if index == limit and limit < len(value):
            return None
        return index

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


def _redact_structured_pairs(value: str, *, embedded_depth: int) -> str:
    result: list[str] = []
    cursor = 0
    index = 0
    while index < len(value):
        if value[index] not in {'"', "'"}:
            index += 1
            continue
        key_end = _quoted_value_end(
            value,
            index,
            limit=min(len(value), index + _MAX_STRUCTURED_VALUE_CHARS),
        )
        if key_end is None:
            index += 1
            continue
        colon = key_end
        while colon < len(value) and value[colon].isspace():
            colon += 1
        if colon >= len(value) or value[colon] != ":":
            index += 1
            continue

        raw_key = value[index + 1 : key_end - 1]
        decoded_key = _decode_structured_key(raw_key)
        secret_key = _secret_key(decoded_key)
        value_start = colon + 1
        while value_start < len(value) and value[value_start].isspace():
            value_start += 1
        if secret_key:
            value_end = _structured_value_end(
                value,
                value_start,
                bare_delimiters=",}])\r\n \t",
            )
            if value_end is not None and _safe_secret_value(
                decoded_key,
                value[value_start:value_end],
                serialized=True,
            ):
                index = value_end
                continue
            result.append(value[cursor:index])
            quote = value[index]
            result.append(f"{quote}{raw_key}{quote}: {_REDACTED}")
            if value_end is None:
                return "".join(result)
            cursor = value_end
            index = value_end
            continue

        if not secret_key:
            if value_start < len(value) and value[value_start] in {'"', "'"}:
                value_end = _structured_value_end(value, value_start)
                if value_end is None:
                    result.append(value[cursor:index])
                    quote = value[index]
                    result.append(f"{quote}{raw_key}{quote}: {_REDACTED}")
                    return "".join(result)
                if _quoted_body_requires_redaction(value[value_start:value_end], embedded_depth=embedded_depth):
                    result.append(value[cursor:index])
                    quote = value[index]
                    result.append(f"{quote}{raw_key}{quote}: {_REDACTED}")
                    cursor = value_end
                    index = value_end
                    continue
            index = key_end
            continue
    result.append(value[cursor:])
    return "".join(result)


def _redact_unquoted_fields(value: str, *, separator: str, embedded_depth: int) -> str:
    result: list[str] = []
    cursor = 0
    index = 0
    while index < len(value):
        if not _field_name_character(value[index]) or (index > 0 and _field_name_character(value[index - 1])):
            index += 1
            continue
        key_end = _field_name_end(value, index)
        delimiter = key_end
        while delimiter < len(value) and value[delimiter].isspace():
            delimiter += 1
        if delimiter >= len(value) or value[delimiter] != separator:
            index = max(key_end, index + 1)
            continue

        key = value[index:key_end]
        value_start = delimiter + 1
        while value_start < len(value) and value[value_start].isspace():
            value_start += 1
        secret_key = _secret_key(key)
        if not secret_key and separator == "=" and value_start < len(value):
            if value[value_start] in {'"', "'"}:
                value_end = _structured_value_end(value, value_start)
                if value_end is None or _quoted_body_requires_redaction(
                    value[value_start:value_end], embedded_depth=embedded_depth
                ):
                    result.append(value[cursor:index])
                    result.append(f"{key}={_REDACTED}")
                    if value_end is None:
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

    if depth > 20:
        return _MAX_DEPTH
    if value is None:
        return value
    if isinstance(value, Enum):
        return redact_secrets(value.value, secrets=secrets, seen=seen, depth=depth)
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"[BYTES:{len(value)}]"
    if isinstance(value, str):
        return redact_string(value, secrets=secrets)

    active = seen if seen is not None else set()
    identity = id(value)
    if identity in active:
        return _CYCLE
    active.add(identity)
    try:
        converted = value
        if isinstance(value, BaseModel):
            try:
                converted = value.model_dump(mode="json")
            except Exception:
                return f"[{type(value).__name__}]"
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            try:
                converted = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
            except Exception:
                return f"[{type(value).__name__}]"

        if isinstance(converted, Mapping):
            result: dict[str, object] = {}
            try:
                entries = islice(converted.items(), _MAX_MAPPING_ITEMS)
                for key, nested in entries:
                    original_name, inspectable = _safe_mapping_key(key)
                    name = redact_string(original_name, secrets=secrets)
                    result[name] = (
                        _REDACTED
                        if not inspectable or _redact_key_value(original_name, nested)
                        else redact_secrets(
                            nested,
                            secrets=secrets,
                            seen=active,
                            depth=depth + 1,
                        )
                    )
            except Exception:
                return f"[{type(value).__name__}]"
            return result

        if isinstance(converted, Iterable):
            result_sequence: list[object] = []
            try:
                for nested in islice(iter(converted), _MAX_SEQUENCE_ITEMS):
                    result_sequence.append(
                        redact_secrets(
                            nested,
                            secrets=secrets,
                            seen=active,
                            depth=depth + 1,
                        )
                    )
            except Exception:
                return f"[{type(value).__name__}]"
            return result_sequence

        return f"[{type(value).__name__}]"
    finally:
        active.remove(identity)
