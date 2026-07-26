from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.security.auth import AuthenticationFailure, CredentialAuthenticator
from app.security.middleware import SecurityAuthorizationMiddleware, mutation_rule


def _config(**values) -> Settings:
    configured = {
        "app_env": "production",
        "security_audit_enabled": False,
        "security_admin_token": "admin-secret",
        "security_codex_token": "codex-secret",
        "security_codex_scopes": "providers:read",
        "security_internal_token": "internal-secret",
        "security_internal_scopes": "jobs:read,jobs:write",
    }
    configured.update(values)
    return Settings(
        _env_file=None,
        **configured,
    )


def test_authenticator_distinguishes_principal_types_and_scopes():
    authenticator = CredentialAuthenticator(_config())

    admin = authenticator.authenticate("Bearer admin-secret", "human_admin")
    codex = authenticator.authenticate("Bearer codex-secret", "codex_service")
    internal = authenticator.authenticate("Bearer internal-secret", "internal_service")

    assert admin.permits("providers:write")
    assert codex.permits("providers:read")
    assert not codex.permits("providers:write")
    assert internal.permits("jobs:write")


def test_authenticator_fails_closed_for_missing_invalid_and_unconfigured_credentials():
    authenticator = CredentialAuthenticator(_config(security_admin_token=None))

    for authorization, expected in ((None, "authentication_required"), ("Basic value", "credential_invalid")):
        try:
            authenticator.authenticate(authorization, "human_admin")
        except AuthenticationFailure as exc:
            assert exc.code == expected
        else:  # pragma: no cover
            raise AssertionError("authentication should fail")

    try:
        authenticator.authenticate("Bearer any", "human_admin")
    except AuthenticationFailure as exc:
        assert exc.code == "authentication_unavailable"
        assert exc.status_code == 503
    else:  # pragma: no cover
        raise AssertionError("authentication should fail closed")


def test_mutation_rules_cover_each_phase_one_scope_without_protecting_reads():
    expected = {
        ("POST", "/brand-profiles"): "settings:write",
        ("POST", "/prompt-templates"): "prompts:write",
        ("PATCH", "/llm-providers/99e6ff1f-96fb-42a7-9a94-a78a7a06539d"): "providers:write",
        ("POST", "/telegram/destinations"): "destinations:write",
        ("PATCH", "/automation-control"): "automations:write",
        ("POST", "/jobs/99e6ff1f-96fb-42a7-9a94-a78a7a06539d/retry"): "jobs:write",
    }
    assert {key: mutation_rule(*key).required_scope for key in expected} == expected
    assert mutation_rule("GET", "/llm-providers") is None


def test_middleware_rejects_missing_credentials_and_scope_but_allows_admin():
    api = FastAPI()
    api.add_middleware(SecurityAuthorizationMiddleware, config=_config())

    @api.post("/llm-providers")
    async def mutate_provider():
        return {"ok": True}

    with TestClient(api) as client:
        missing = client.post("/llm-providers")
        denied = client.post(
            "/llm-providers",
            headers={
                "Authorization": "Bearer codex-secret",
                "X-NewsCraft-Principal-Type": "codex_service",
            },
        )
        allowed = client.post(
            "/llm-providers",
            headers={"Authorization": "Bearer admin-secret"},
        )

    assert missing.status_code == 401
    assert missing.json() == {"detail": {"code": "authentication_required"}}
    assert denied.status_code == 403
    assert denied.json() == {"detail": {"code": "scope_denied"}}
    assert allowed.status_code == 200
