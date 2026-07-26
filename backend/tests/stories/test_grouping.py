from datetime import UTC, datetime, timedelta

from app.stories.grouping import GroupingInput, decide_group, group_components


def item(item_id: str, title: str, url: str, hours: int = 0) -> GroupingInput:
    return GroupingInput(
        content_item_id=item_id,
        title=title,
        canonical_url=url,
        published_at=datetime(2026, 7, 11, 8, tzinfo=UTC) + timedelta(hours=hours),
    )


def test_same_canonical_url_groups_even_when_titles_differ():
    result = decide_group(
        item("a", "OpenAI ships a new agent", "https://example.com/news?id=7"),
        item("b", "New coding agent arrives", "https://example.com/news?id=7&utm_source=rss"),
    )

    assert result.grouped is True
    assert result.reason == "canonical_url"
    assert result.score == 1.0


def test_related_titles_group_inside_72_hour_window():
    result = decide_group(
        item("a", "OpenAI releases new coding agent for developers", "https://a.example/story"),
        item(
            "b",
            "OpenAI releases a coding agent for software developers",
            "https://b.example/story",
            hours=8,
        ),
    )

    assert result.grouped is True
    assert result.reason == "title_similarity"
    assert result.score >= 0.72


def test_old_or_weakly_related_items_do_not_merge():
    result = decide_group(
        item("a", "OpenAI releases new coding agent", "https://a.example/story"),
        item("b", "Global chip sales rise", "https://b.example/story", hours=96),
    )

    assert result.grouped is False
    assert result.reason == "insufficient_similarity"


def test_empty_normalized_titles_have_zero_similarity():
    result = decide_group(
        item("a", "! ? a", "https://a.example/story"),
        item("b", ". , I", "https://b.example/story"),
    )

    assert result.grouped is False
    assert result.score == 0.0


def test_group_components_is_pure_and_transitive():
    values = [
        item("a", "First", "https://example.com/shared"),
        item("b", "Second", "https://example.com/shared?utm_source=feed"),
        item("c", "Third", "https://example.com/other"),
    ]

    assert group_components(values) == ((0, 1), (2,))
