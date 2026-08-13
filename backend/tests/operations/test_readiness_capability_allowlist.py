from __future__ import annotations

import pytest

from app.core.config import READINESS_CAPABILITIES, Settings
from app.operations.health import _configured_capabilities, _safe_capabilities


def test_settings_accept_every_shared_capability() -> None:
    value = ",".join(sorted(READINESS_CAPABILITIES))
    settings = Settings(readiness_required_capabilities=value)
    assert _configured_capabilities(settings.readiness_required_capabilities) == tuple(
        sorted(READINESS_CAPABILITIES)
    )


def test_settings_reject_a_capability_the_health_filter_would_drop() -> None:
    with pytest.raises(ValueError):
        Settings(readiness_required_capabilities="teleportation")
    assert _safe_capabilities(["teleportation"]) == ()


def test_health_filter_and_settings_share_one_allow_list() -> None:
    """Readiness must not require a capability a component may never advertise."""
    for capability in READINESS_CAPABILITIES:
        settings = Settings(readiness_required_capabilities=capability)
        required = _configured_capabilities(settings.readiness_required_capabilities)
        assert required == (capability,)
        assert _safe_capabilities([capability]) == (capability,)
