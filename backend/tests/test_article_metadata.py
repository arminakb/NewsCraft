from app.content.article_metadata import (
    canonical_content_type,
    canonical_language,
    canonical_topic,
)


def test_dimension_normalizers_use_stable_supported_casing():
    assert canonical_content_type(" ReSearch ") == "research"
    assert canonical_topic(" ai ") == "AI"
    assert canonical_topic("TECH") == "Tech"
    assert canonical_topic("general") is None
    assert canonical_language(" FA ") == "fa"
