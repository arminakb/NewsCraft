import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.security.auth import AuthenticationFailure, CredentialAuthenticator
from app.security.middleware import SecurityAuthorizationMiddleware, mutation_rule


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


def test_authenticator_derives_service_identity_and_scopes_from_server_tokens():
    authenticator = CredentialAuthenticator(_config())

    codex = authenticator.authenticate("Bearer codex-secret")
    internal = authenticator.authenticate("Bearer internal-secret")

    assert codex.principal_type == "codex_service"
    assert codex.permits("providers:read")
    assert not codex.permits("providers:write")
    assert internal.principal_type == "internal_service"
    assert internal.permits("jobs:write")


def test_authenticator_fails_closed_for_missing_invalid_and_ambiguous_credentials():
    for config, authorization, expected in (
        (_config(), None, "authentication_required"),
        (_config(), "Basic value", "credential_invalid"),
        (_config(), "Bearer unknown", "credential_invalid"),
        (
            _config(security_codex_token="shared", security_internal_token="shared"),
            "Bearer shared",
            "credential_invalid",
        ),
    ):
        with pytest.raises(AuthenticationFailure) as caught:
            CredentialAuthenticator(config).authenticate(authorization)
        assert caught.value.code == expected


def test_mutation_rules_use_one_resource_specific_scope_per_settings_resource():
    expected = {
        ("POST", "/brand-profiles"): "settings:write",
        ("POST", "/prompt-templates"): "prompts:write",
        ("POST", "/prompt-templates/id/versions"): "prompts:write",
        ("POST", "/llm-providers"): "providers:write",
        ("DELETE", "/llm-providers/99e6ff1f-96fb-42a7-9a94-a78a7a06539d"): "providers:write",
        ("POST", "/telegram/destinations"): "destinations:write",
        ("PATCH", "/telegram/proxies/id"): "destinations:write",
        ("POST", "/telegram/automations"): "automations:write",
        ("POST", "/automations"): "automations:write",
        ("PATCH", "/automations/99e6ff1f-96fb-42a7-9a94-a78a7a06539d"): "automations:write",
        ("POST", "/automations/99e6ff1f-96fb-42a7-9a94-a78a7a06539d/versions"): "automations:write",
        (
            "POST",
            "/automations/99e6ff1f-96fb-42a7-9a94-a78a7a06539d/versions/1/validate",
        ): "automations:write",
        ("PATCH", "/automation-control"): "automations:write",
        ("PUT", "/operator-settings/date-time"): "settings:write",
        ("PUT", "/operations/retention-policy"): "settings:write",
        ("POST", "/operations/retention-preview"): "settings:write",
        ("POST", "/operations/retention-runs"): "settings:write",
        ("POST", "/jobs/99e6ff1f-96fb-42a7-9a94-a78a7a06539d/retry"): "jobs:write",
        ("POST", "/feed/clear"): "feed:write",
    }
    assert {key: mutation_rule(*key).required_scope for key in expected} == expected
    assert mutation_rule("GET", "/llm-providers") is None
    assert mutation_rule("POST", "/automation-resource-catalog") is None


def _provider_app(config: Settings) -> FastAPI:
    api = FastAPI()
    api.add_middleware(SecurityAuthorizationMiddleware, config=config)

    @api.post("/llm-providers")
    async def mutate_provider(request: Request):
        principal = request.state.security_principal
        return {"principal_type": principal.principal_type, "principal_id": principal.principal_id}

    return api


async def test_local_owner_is_server_created_and_ignores_client_roles_scopes_and_forwarding_headers():
    api = _provider_app(_config())

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post(
            "/llm-providers",
            headers={
                "Origin": "http://localhost:3000",
                "X-NewsCraft-Principal-Type": "human_admin",
                "X-NewsCraft-Scopes": "jobs:write",
                "X-Forwarded-For": "203.0.113.10",
                "X-Forwarded-Host": "attacker.example",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"principal_type": "local_owner", "principal_id": "local-owner"}


async def test_local_owner_mutations_require_valid_allowed_origin():
    api = _provider_app(_config())

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        allowed = await client.post("/llm-providers", headers={"Origin": "http://127.0.0.1:3000"})
        missing = await client.post("/llm-providers")
        cross_origin = await client.post("/llm-providers", headers={"Origin": "https://attacker.example"})
        malformed = await client.post("/llm-providers", headers={"Origin": "http://localhost:not-a-port"})

    assert allowed.status_code == 200
    for response in (missing, cross_origin, malformed):
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "origin_validation_failed"}}


async def test_profile_mode_fails_closed_while_bearer_service_authentication_remains_available():
    api = _provider_app(_config(
        application_auth_mode="profile",
        cors_origins="https://newscraft.example",
        security_codex_scopes="providers:write",
    ))

    async with AsyncClient(transport=ASGITransport(app=api), base_url="https://newscraft.example") as client:
        browser = await client.post("/llm-providers", headers={"Origin": "https://newscraft.example"})
        spoofed = await client.post(
            "/llm-providers",
            headers={"X-NewsCraft-Principal-Type": "local_owner", "X-NewsCraft-Scopes": "providers:write"},
        )
        service = await client.post(
            "/llm-providers",
            headers={
                "Authorization": "Bearer codex-secret",
                "Origin": "https://attacker.example",
                "X-NewsCraft-Principal-Type": "human_admin",
            },
        )

    assert browser.status_code == 401
    assert spoofed.status_code == 401
    assert browser.json() == {"detail": {"code": "authentication_required"}}
    assert service.status_code == 200
    assert service.json()["principal_type"] == "codex_service"


def test_local_owner_configuration_rejects_public_or_malformed_origins():
    for origins in ("https://newscraft.example", "http://localhost:not-a-port", ""):
        with pytest.raises(ValidationError, match="loopback-only CORS origins"):
            _config(cors_origins=origins)

    profile = _config(application_auth_mode="profile", cors_origins="https://newscraft.example")
    assert profile.application_auth_mode == "profile"
