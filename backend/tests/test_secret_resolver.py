from __future__ import annotations

import pytest

from app.core.secrets import (
    EnvironmentSecretResolver,
    FileSecretResolver,
    SecretFileSecurityError,
    SecretNotConfiguredError,
    SecretReferenceError,
    SecretResolver,
    build_worker_secret_resolver,
)


def test_environment_secret_resolver_returns_only_explicit_reference(monkeypatch):
    monkeypatch.setenv("OPENROUTER_EDITOR_KEY", "real-secret")
    monkeypatch.setenv("OPENROUTER_OTHER_KEY", "other-secret")
    resolver = EnvironmentSecretResolver()

    assert resolver.configured("OPENROUTER_EDITOR_KEY") is True
    assert resolver.resolve("OPENROUTER_EDITOR_KEY") == "real-secret"


def test_injected_environment_mapping_is_the_only_source(monkeypatch):
    monkeypatch.setenv("OPENROUTER_EDITOR_KEY", "process-secret")
    resolver = EnvironmentSecretResolver({"INJECTED_KEY": "injected-secret"})

    assert resolver.configured("OPENROUTER_EDITOR_KEY") is False
    assert resolver.resolve("INJECTED_KEY") == "injected-secret"


def test_missing_and_invalid_references_never_leak_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_EDITOR_KEY", "real-secret")
    resolver = EnvironmentSecretResolver()

    assert resolver.configured("MISSING_KEY") is False
    with pytest.raises(SecretNotConfiguredError, match="MISSING_KEY") as missing:
        resolver.resolve("MISSING_KEY")
    with pytest.raises(SecretReferenceError) as invalid:
        resolver.resolve("not-valid")
    assert "real-secret" not in str(missing.value)
    assert "real-secret" not in repr(missing.value)
    assert "real-secret" not in str(invalid.value)
    assert "real-secret" not in repr(invalid.value)


def test_invalid_reference_error_does_not_echo_supplied_material():
    supplied_material = "literal-secret-value"
    resolver = EnvironmentSecretResolver({})

    with pytest.raises(SecretReferenceError) as invalid:
        resolver.resolve(supplied_material)

    assert supplied_material not in str(invalid.value)
    assert supplied_material not in repr(invalid.value)


@pytest.mark.parametrize(
    "reference",
    [
        "AB",
        "a_VALID_KEY",
        "1_INVALID_KEY",
        "INVALID-KEY",
        "VALID_KEY\nINJECTED",
        "A" * 129,
        "",
    ],
)
def test_reference_validation_uses_strict_full_match(reference):
    resolver = EnvironmentSecretResolver({})

    with pytest.raises(SecretReferenceError):
        resolver.configured(reference)
    with pytest.raises(SecretReferenceError):
        resolver.resolve(reference)


def test_three_character_reference_is_valid():
    resolver = EnvironmentSecretResolver({"A_1": "secret"})

    assert resolver.configured("A_1") is True
    assert resolver.resolve("A_1") == "secret"


def test_empty_value_check_strips_but_resolution_returns_original_value():
    resolver = EnvironmentSecretResolver({"SPACE_ONLY": " \t ", "PADDED_KEY": "  secret value  "})

    assert resolver.configured("SPACE_ONLY") is False
    with pytest.raises(SecretNotConfiguredError, match="SPACE_ONLY"):
        resolver.resolve("SPACE_ONLY")
    assert resolver.configured("PADDED_KEY") is True
    assert resolver.resolve("PADDED_KEY") == "  secret value  "


def test_environment_resolver_satisfies_public_protocol():
    resolver: SecretResolver = EnvironmentSecretResolver({"VALID_KEY": "secret"})

    assert resolver.configured("VALID_KEY") is True


def test_file_secret_resolver_reads_each_time_for_rotation(tmp_path):
    secret = tmp_path / "OPENROUTER_API_KEY"
    secret.write_text("first-canary\n", encoding="utf-8")
    secret.chmod(0o400)
    resolver = FileSecretResolver(tmp_path)

    assert resolver.resolve("OPENROUTER_API_KEY") == "first-canary"
    secret.chmod(0o600)
    secret.write_text("rotated-canary\n", encoding="utf-8")
    secret.chmod(0o400)
    assert resolver.resolve("OPENROUTER_API_KEY") == "rotated-canary"


def test_file_secret_resolver_rejects_symlinks_and_broad_permissions(tmp_path):
    broad = tmp_path / "BROAD_SECRET"
    broad.write_text("broad-canary", encoding="utf-8")
    broad.chmod(0o644)
    resolver = FileSecretResolver(tmp_path)

    with pytest.raises(SecretFileSecurityError):
        resolver.resolve("BROAD_SECRET")

    target = tmp_path / "target"
    target.write_text("symlink-canary", encoding="utf-8")
    target.chmod(0o400)
    (tmp_path / "LINK_SECRET").symlink_to(target)
    with pytest.raises(SecretNotConfiguredError):
        resolver.resolve("LINK_SECRET")


def test_production_worker_ignores_environment_fallback(tmp_path):
    resolver = build_worker_secret_resolver(
        app_env="production",
        secret_root=tmp_path,
        environ={"TELEGRAM_DESTINATION_NEWS_TOKEN": "environment-canary"},
    )

    assert resolver.configured("TELEGRAM_DESTINATION_NEWS_TOKEN") is False
    with pytest.raises(SecretNotConfiguredError):
        resolver.resolve("TELEGRAM_DESTINATION_NEWS_TOKEN")


def test_production_workers_resolve_every_owned_category_and_reject_other_worker_files(
    tmp_path,
):
    source_root = tmp_path / "source"
    publishing_root = tmp_path / "publishing"
    source_root.mkdir()
    publishing_root.mkdir()
    source_secret = source_root / "OPENROUTER_API_KEY"
    source_api_id = source_root / "TELEGRAM_SOURCE_EDITOR_API_ID"
    source_proxy = source_root / "HTTP_PROXY"
    destination_secret = publishing_root / "TELEGRAM_DESTINATION_NEWS_TOKEN"
    publishing_proxy = publishing_root / "HTTP_PROXY"
    source_secret.write_text("provider-canary", encoding="utf-8")
    source_api_id.write_text("source-canary", encoding="utf-8")
    source_proxy.write_text("http://source-proxy-canary.example:8080", encoding="utf-8")
    destination_secret.write_text("destination-canary", encoding="utf-8")
    publishing_proxy.write_text("http://publishing-proxy-canary.example:8080", encoding="utf-8")
    for secret in (
        source_secret,
        source_api_id,
        source_proxy,
        destination_secret,
        publishing_proxy,
    ):
        secret.chmod(0o400)

    source = build_worker_secret_resolver(app_env="production", secret_root=source_root, environ={})
    publishing = build_worker_secret_resolver(app_env="production", secret_root=publishing_root, environ={})

    assert source.resolve("OPENROUTER_API_KEY") == "provider-canary"
    assert source.resolve("TELEGRAM_SOURCE_EDITOR_API_ID") == "source-canary"
    assert source.resolve("HTTP_PROXY") == "http://source-proxy-canary.example:8080"
    assert publishing.resolve("TELEGRAM_DESTINATION_NEWS_TOKEN") == "destination-canary"
    assert publishing.resolve("HTTP_PROXY") == ("http://publishing-proxy-canary.example:8080")
    with pytest.raises(SecretNotConfiguredError):
        source.resolve("TELEGRAM_DESTINATION_NEWS_TOKEN")
    with pytest.raises(SecretNotConfiguredError):
        publishing.resolve("OPENROUTER_API_KEY")
