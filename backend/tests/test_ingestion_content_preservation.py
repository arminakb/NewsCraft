from types import SimpleNamespace

from app.ingestion.repository import _preserve_more_complete_content


def test_duplicate_ingestion_does_not_replace_longer_canonical_content() -> None:
    existing = SimpleNamespace(
        content_text="Full stored article body with several complete paragraphs.",
        content_html_sanitized="<p>Full stored article body with several complete paragraphs.</p>",
        metrics={"content_origin": "source_provided", "classification": {"category": "AI"}},
    )
    incoming = {
        "content_text": "Short excerpt.",
        "content_html_sanitized": "<p>Short excerpt.</p>",
        "metrics": {"content_origin": "source_excerpt", "classification": {"category": "Tech"}},
    }

    merged = _preserve_more_complete_content(existing, incoming)

    assert merged["content_text"] == existing.content_text
    assert merged["content_html_sanitized"] == existing.content_html_sanitized
    assert merged["metrics"]["content_origin"] == "source_provided"
    assert merged["metrics"]["classification"] == {"category": "Tech"}


def test_duplicate_ingestion_accepts_more_complete_content() -> None:
    existing = SimpleNamespace(
        content_text="Short excerpt.",
        content_html_sanitized="<p>Short excerpt.</p>",
        metrics={"content_origin": "source_excerpt"},
    )
    incoming = {
        "content_text": "Longer source-provided article body with useful editorial detail.",
        "content_html_sanitized": "<p>Longer source-provided article body with useful editorial detail.</p>",
        "metrics": {"content_origin": "source_provided"},
    }

    assert _preserve_more_complete_content(existing, incoming) is incoming
