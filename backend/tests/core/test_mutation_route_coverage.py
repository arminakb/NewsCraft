"""Default-deny coverage of the mutating route table.

The security middleware authorizes mutations by path. Before this suite the
table was an allowlist whose terminal branch returned ``None``, which skipped
authentication, same-origin/CSRF validation and audit for every route nobody
had remembered to list. These tests pin the inverse contract: every mutating
route on the real application yields a rule, and the handful of deliberate
exemptions is enumerated here so a new router cannot join it silently.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app as application
from app.security.middleware import (
    MUTATION_METHODS,
    UNRULED_MUTATION_PATHS,
    SecurityAuthorizationMiddleware,
    mutation_rule,
)

# Every path in this set authenticates inside its own handler. Extending it is a
# security decision and must be argued in review, never in a route decorator.
EXPECTED_UNRULED_PATHS = {
    ("automation-resource-catalog",),
    ("codex-gateway", "pair"),
    ("codex-gateway", "heartbeat"),
}


def _routes(routes, prefix: str = "") -> set[tuple[str, str]]:
    """Collect ``(method, full path)`` pairs, following included sub-routers.

    Includes routes hidden from OpenAPI: an undocumented mutation is exactly the
    kind this contract must still cover.
    """
    collected: set[tuple[str, str]] = set()
    for route in routes:
        if isinstance(route, APIRoute):
            collected.update((method, prefix + route.path) for method in route.methods)
            continue
        include_context = getattr(route, "include_context", None)
        if include_context is not None:
            collected |= _routes(include_context.included_router.routes, prefix + include_context.prefix)
            continue
        nested = getattr(route, "routes", None)
        if nested:
            collected |= _routes(nested, prefix + getattr(route, "path", ""))
    return collected


def _mutating_routes() -> set[tuple[str, str]]:
    return {(method, path) for method, path in _routes(application.routes) if method in MUTATION_METHODS}


def test_route_table_walk_finds_the_documented_application_surface():
    mutating = _mutating_routes()

    assert len(mutating) > 90
    assert ("POST", "/sources/seed") in mutating
    assert ("POST", "/telegram/drafts/{revision_id}/publish") in mutating
    assert ("POST", "/llm-providers") in mutating


def test_every_mutating_route_yields_a_rule_except_the_enumerated_exemptions():
    uncovered = sorted(
        f"{method} {path}" for method, path in _mutating_routes() if mutation_rule(method, path) is None
    )

    assert uncovered == sorted(f"POST /{'/'.join(parts)}" for parts in EXPECTED_UNRULED_PATHS)


def test_exemption_set_is_closed_and_matches_the_middleware_constant():
    assert UNRULED_MUTATION_PATHS == EXPECTED_UNRULED_PATHS
    # Exemptions are exact paths: a nested route never inherits one.
    assert mutation_rule("POST", "/codex-gateway/pair/anything") is not None


def test_every_rule_requires_a_scope_the_owner_actually_holds():
    from app.security.scopes import APPLICATION_OWNER_SCOPES

    for method, path in _mutating_routes():
        rule = mutation_rule(method, path)
        if rule is None:
            continue
        assert rule.required_scope in APPLICATION_OWNER_SCOPES, f"{method} {path}"
        assert rule.resource_type, f"{method} {path}"
        assert rule.action.startswith(f"{rule.resource_type}."), f"{method} {path}"


def _config(**values) -> Settings:
    configured = {
        "app_env": "production",
        "application_auth_mode": "local_owner",
        "cors_origins": "http://localhost:3000,http://127.0.0.1:3000",
        "security_audit_enabled": False,
        "security_codex_token": "codex-secret",
        "security_codex_scopes": "providers:read",
        "security_internal_token": "internal-secret",
        "security_internal_scopes": "jobs:read,jobs:write",
    }
    configured.update(values)
    return Settings(_env_file=None, **configured)


def _seed_app(config: Settings) -> FastAPI:
    """The real middleware in front of a previously unauthorized route."""

    api = FastAPI()
    api.add_middleware(SecurityAuthorizationMiddleware, config=config)

    @api.post("/sources/seed")
    async def seed_sources(request: Request):
        principal = request.state.security_principal
        return {"principal_type": principal.principal_type}

    return api


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        ({}, "origin_validation_failed"),
        ({"Origin": "https://attacker.example"}, "origin_validation_failed"),
    ],
)
async def test_body_less_post_now_fails_cross_origin_form_submission(headers, expected_code):
    """POST /sources/seed takes no body, so it was reachable by a plain HTML form."""

    api = _seed_app(_config())

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post("/sources/seed", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": expected_code}}


async def test_previously_uncovered_route_admits_the_same_origin_owner():
    api = _seed_app(_config())

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post("/sources/seed", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.json() == {"principal_type": "local_owner"}


async def test_previously_uncovered_route_denies_a_service_token_without_the_scope():
    api = _seed_app(_config())

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        denied = await client.post(
            "/sources/seed",
            headers={"Authorization": "Bearer internal-secret", "Origin": "http://localhost:3000"},
        )
        granted = await client.post(
            "/sources/seed",
            headers={"Authorization": "Bearer unknown-token", "Origin": "http://localhost:3000"},
        )

    assert denied.status_code == 403
    assert denied.json() == {"detail": {"code": "scope_denied"}}
    assert granted.status_code == 401
    assert granted.json() == {"detail": {"code": "credential_invalid"}}
