from __future__ import annotations

from app.content_production.tracing import sanitize_snapshot


def test_snapshot_sanitization_redacts_recursive_secret_key_variants():
    snapshot = sanitize_snapshot(
        {
            "headers": {
                "Authorization": "Bearer auth-secret",
                "Proxy-Authorization": "Basic proxy-secret",
                "Cookie": "session=cookie-secret",
                "Set-Cookie": "session=set-cookie-secret",
                "X-API-Key": "header-api-key",
            },
            "nested": [
                {
                    "apikey": "compact-api-key",
                    "private_key": "private-key",
                    "session": "session-secret",
                    "auth_token": "auth-token",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "bot_token": "bot-token",
                    "provider_key": "provider-key",
                    "credentials": {"username": "operator", "password": "password"},
                }
            ],
        }
    )

    serialized = str(snapshot)
    for secret in (
        "auth-secret",
        "proxy-secret",
        "cookie-secret",
        "set-cookie-secret",
        "header-api-key",
        "compact-api-key",
        "private-key",
        "session-secret",
        "auth-token",
        "access-token",
        "refresh-token",
        "bot-token",
        "provider-key",
        "operator",
        "password",
    ):
        assert secret not in serialized


def test_sensitive_prompt_and_provider_payload_have_no_excerpt():
    snapshot = sanitize_snapshot(
        {
            "prompt": "Authorization: Bearer embedded-secret\nWrite an article",
            "provider_request": {"value": "embedded-provider-secret", "model": "provider-model"},
        }
    )

    assert snapshot["prompt"]["redacted"] is True
    assert snapshot["provider_request"]["redacted"] is True
    assert "excerpt" not in snapshot["prompt"]
    assert "excerpt" not in snapshot["provider_request"]
    assert "embedded-secret" not in str(snapshot)
    assert "embedded-provider-secret" not in str(snapshot)


def test_large_article_text_remains_bounded_and_operationally_useful():
    article = "Public article summary. " * 100

    snapshot = sanitize_snapshot({"content_text": article, "content_item_id": "item-123", "decision": "sufficient"})

    assert snapshot["content_item_id"] == "item-123"
    assert snapshot["decision"] == "sufficient"
    assert snapshot["content_text"]["length"] == len(article)
    assert len(snapshot["content_text"]["sha256"]) == 64
    assert snapshot["content_text"]["excerpt"] == article[:80]
