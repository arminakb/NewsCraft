from __future__ import annotations

import pytest

from app.core.secrets import (
    EnvironmentSecretResolver,
    SecretNotConfiguredError,
    SecretReferenceError,
    SecretResolver,
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
