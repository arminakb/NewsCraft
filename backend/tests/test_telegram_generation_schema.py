from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramRewriteOutput,
    TelegramVariantContent,
)


def test_telegram_output_rejects_unbounded_or_unsupported_content():
    with pytest.raises(ValidationError):
        TelegramRewriteOutput(body="x" * 4097, parse_mode="HTML", buttons=[])
    with pytest.raises(ValidationError):
        TelegramRewriteOutput(body="<script>alert(1)</script>", parse_mode="HTML", buttons=[])
    with pytest.raises(ValidationError):
        TelegramRewriteOutput(body='<a href="javascript:alert(1)">unsafe</a>', parse_mode="HTML", buttons=[])
    for malformed in ("<b>x</i>", "</b>orphan", "<b/>x", "<!--comment--><b>x</b>"):
        with pytest.raises(ValidationError):
            TelegramRewriteOutput(body=malformed, parse_mode="HTML", buttons=[])
    for unsupported in (
        "<!DOCTYPE html><b>x</b>",
        "<?xml version='1.0'?><b>x</b>",
        "<![CDATA[x]]><b>x</b>",
        '<a href="https://user:pass@example.com">x</a>',
    ):
        with pytest.raises(ValidationError):
            TelegramRewriteOutput(body=unsupported, parse_mode="HTML", buttons=[])
    with pytest.raises(ValidationError):
        TelegramRewriteOutput(
            body="safe",
            parse_mode="HTML",
            buttons=[{"text": "unsafe", "url": "https://user:pass@example.com"}],
        )


def test_telegram_output_accepts_allowlisted_html_and_https_buttons():
    value = TelegramRewriteOutput.model_validate(
        {
            "body": '<blockquote><strong>خبر</strong> <a href="https://example.com/x">منبع</a></blockquote>',
            "parse_mode": "HTML",
            "buttons": [{"text": "Read", "url": "https://example.com"}],
        }
    )
    assert value.parse_mode == "HTML"


def test_shared_telegram_variant_allows_truthful_null_source_item_identity():
    value = TelegramVariantContent.model_validate(
        {
            "body": "Operator-authored Telegram draft",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": "omit",
            "media_asset_ids": [],
            "direction": "ltr",
            "dry_run": False,
        }
    )
    assert value.source_item_id is None


def test_evidence_citation_is_exact_and_hash_bounded():
    value = TelegramEvidenceCitation(
        evidence_snapshot_id=uuid4(),
        evidence_key="snapshot:1",
        source_url="https://example.com/story",
        locator="chars:0-12",
        excerpt_sha256="a" * 64,
    )
    assert value.locator == "chars:0-12"
    with pytest.raises(ValidationError):
        TelegramEvidenceCitation(
            evidence_snapshot_id=uuid4(),
            evidence_key="snapshot:1",
            source_url=None,
            locator="line:1",
            excerpt_sha256="bad",
        )
