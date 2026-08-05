from __future__ import annotations

ALL_SCOPES = frozenset(
    {
        "settings:read",
        "settings:write",
        "providers:read",
        "providers:write",
        "destinations:read",
        "destinations:write",
        "prompts:read",
        "prompts:write",
        "automations:read",
        "automations:write",
        "jobs:read",
        "jobs:write",
    }
)

APPLICATION_OWNER_SCOPES = ALL_SCOPES


def parse_scopes(value: str) -> frozenset[str]:
    scopes = frozenset(part.strip().casefold() for part in value.split(",") if part.strip())
    if scopes - ALL_SCOPES:
        raise ValueError("unsupported security scope")
    return scopes


__all__ = ["ALL_SCOPES", "APPLICATION_OWNER_SCOPES", "parse_scopes"]
