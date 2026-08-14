from __future__ import annotations

import re

_EXTERNAL_REFERENCE = re.compile(
    r"(?:xlink:)?(?:href|src)\s*=\s*['\"]\s*(?:https?:|//|data:|javascript:|vbscript:)",
    re.I,
)
_EXTERNAL_CSS = re.compile(r"url\(\s*['\"]?\s*(?:https?:|//|data:|javascript:|vbscript:)", re.I)
_EVENT_HANDLER = re.compile(r"\son[a-z0-9_-]+\s*=", re.I)
_UNSAFE_ELEMENT = re.compile(r"<\s*(script|foreignObject)\b", re.I)


def is_safe_svg(body: bytes) -> bool:
    text = body.decode("utf-8", errors="replace")
    return not any(
        pattern.search(text) for pattern in (_EVENT_HANDLER, _EXTERNAL_REFERENCE, _EXTERNAL_CSS, _UNSAFE_ELEMENT)
    )
