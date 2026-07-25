from app.content.article_metadata import (
    canonical_content_type,
    canonical_language,
    canonical_topic,
    canonicalize_article_classification,
)


def test_canonical_article_classification_resolves_generic_news_overlap():
    classification = canonicalize_article_classification(
        content_type="  Article ",
        topic=" news ",
        language=" EN ",
    )

    assert classification.content_type == "news"
    assert classification.topic is None
    assert classification.language == "en"


def test_canonical_article_classification_deduplicates_identical_values():
    classification = canonicalize_article_classification(
        content_type="NEWS",
        topic="News",
        language="fa",
    )

    assert classification.content_type == "news"
    assert classification.topic is None
    assert classification.language == "fa"


def test_canonical_article_classification_hides_general_and_preserves_nulls():
    classification = canonicalize_article_classification(
        content_type=None,
        topic=" General ",
        language=None,
    )

    assert classification.content_type is None
    assert classification.topic is None
    assert classification.language is None


def test_unknown_values_are_trimmed_casefolded_and_not_inferred():
    classification = canonicalize_article_classification(
        content_type=" Field   Report ",
        topic=" Public  Policy ",
        language=" ZZ ",
    )

    assert classification.content_type == "field report"
    assert classification.topic == "public policy"
    assert classification.language == "zz"


def test_dimension_normalizers_use_stable_supported_casing():
    assert canonical_content_type(" ReSearch ") == "research"
    assert canonical_topic(" ai ") == "AI"
    assert canonical_topic("TECH") == "Tech"
    assert canonical_topic("general") is None
    assert canonical_language(" FA ") == "fa"
