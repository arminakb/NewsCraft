from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DetectedImage:
    mime_type: str
    width: int
    height: int


def normalized_content_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.split(";", 1)[0].strip().casefold()
    return normalized or None


def sniff_image_format(body: bytes) -> str | None:
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    if body.startswith(b"\x00\x00\x01\x00"):
        return "image/vnd.microsoft.icon"
    if re.search(rb"<svg\b", body[:16_384], re.I):
        return "image/svg+xml"
    return None


def sniff_image(body: bytes) -> DetectedImage | None:
    mime_type = sniff_image_format(body)
    parsers: dict[str, Callable[[bytes], tuple[int, int] | None]] = {
        "image/png": _png_dimensions,
        "image/gif": _gif_dimensions,
        "image/jpeg": _jpeg_dimensions,
        "image/webp": _webp_dimensions,
        "image/vnd.microsoft.icon": _ico_dimensions,
        "image/svg+xml": _svg_dimensions,
    }
    dimensions = parsers[mime_type](body) if mime_type is not None else None
    if mime_type is None or dimensions is None:
        return None
    return DetectedImage(mime_type, dimensions[0], dimensions[1])


def _png_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
        return None
    return int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")


def _gif_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 10 or body[:6] not in {b"GIF87a", b"GIF89a"}:
        return None
    return int.from_bytes(body[6:8], "little"), int.from_bytes(body[8:10], "little")


def _jpeg_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 4 or body[:2] != b"\xff\xd8":
        return None
    offset = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while offset + 4 <= len(body):
        if body[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(body) and body[offset] == 0xFF:
            offset += 1
        if offset >= len(body):
            break
        marker = body[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(body):
            break
        length = int.from_bytes(body[offset : offset + 2], "big")
        if length < 2 or offset + length > len(body):
            break
        if marker in sof_markers and length >= 7:
            return int.from_bytes(body[offset + 5 : offset + 7], "big"), int.from_bytes(
                body[offset + 3 : offset + 5], "big"
            )
        offset += length
    return None


def _webp_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 16 or body[:4] != b"RIFF" or body[8:12] != b"WEBP":
        return None
    chunk = body[12:16]
    if chunk == b"VP8X" and len(body) >= 30:
        width = 1 + int.from_bytes(body[24:27], "little")
        height = 1 + int.from_bytes(body[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(body) >= 30:
        marker = body.find(b"\x9d\x01\x2a", 16)
        if marker >= 0 and marker + 7 <= len(body):
            return int.from_bytes(body[marker + 3 : marker + 5], "little") & 0x3FFF, int.from_bytes(
                body[marker + 5 : marker + 7], "little"
            ) & 0x3FFF
    return None


def _ico_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 22 or body[:4] != b"\x00\x00\x01\x00" or int.from_bytes(body[4:6], "little") < 1:
        return None
    return body[6] or 256, body[7] or 256


def _svg_dimensions(body: bytes) -> tuple[int, int] | None:
    text = body.decode("utf-8", errors="replace")
    root = re.search(r"<svg\b([^>]*)>", text[:16_384], re.I | re.S)
    if not root:
        return None
    attributes = {
        name.casefold(): value.strip()
        for name, value in re.findall(r"\b(width|height|viewBox)\s*=\s*['\"]([^'\"]+)['\"]", root.group(1), re.I)
    }
    view_box = attributes.get("viewbox")
    if view_box:
        values = re.split(r"[\s,]+", view_box)
        if len(values) == 4:
            try:
                return max(1, round(float(values[2]))), max(1, round(float(values[3])))
            except ValueError:
                pass
    dimensions: list[int] = []
    for key in ("width", "height"):
        match = re.match(r"([0-9]+(?:\.[0-9]+)?)", attributes.get(key, ""))
        if not match:
            return None
        dimensions.append(max(1, round(float(match.group(1)))))
    if len(dimensions) != 2:
        return None
    return dimensions[0], dimensions[1]
