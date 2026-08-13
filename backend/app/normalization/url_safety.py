"""Shared deny-list for outbound URLs harvested from third-party content.

Icon discovery and media downloading both fetch URLs that arrive inside remote
documents, so both need the same answer to "may NewsCraft dial this host?".
The rules live here — in a leaf module neither package owns — so the two call
sites can never drift apart.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

BLOCKED_HOSTS = frozenset(
    {
        "instance-data",
        "localhost",
        "metadata",
        "metadata.google.internal",
        "host.docker.internal",
    }
)
BLOCKED_HOST_SUFFIXES = (".internal", ".localhost", ".local", ".home.arpa", ".intranet")


class UnsafeUrlError(ValueError):
    """The URL points at a local, private, metadata, or credentialed target."""


def validate_public_http_url(value: str) -> str:
    """Return the URL unchanged, or raise if it must never be requested."""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("unsafe_url")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("unsafe_url")
    hostname = parsed.hostname.rstrip(".").casefold()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname in BLOCKED_HOSTS or hostname.endswith(BLOCKED_HOST_SUFFIXES):
            raise UnsafeUrlError("unsafe_url") from None
    else:
        if not address.is_global:
            raise UnsafeUrlError("unsafe_url")
    return value


__all__ = ["BLOCKED_HOSTS", "BLOCKED_HOST_SUFFIXES", "UnsafeUrlError", "validate_public_http_url"]
