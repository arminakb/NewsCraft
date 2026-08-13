from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentItem, ItemMedia, MediaAsset, Source
from app.db.session import get_session
from app.main import app
from app.stories.models import Story, StoryEvidenceSnapshot

NOW = datetime(2026, 7, 21, 8, tzinfo=UTC)


async def test_articles_summary_and_detail_contracts_are_composed_and_bounded(db_session: AsyncSession):
    source = Source(
        platform="rss",
        name="Joined Wire",
        feed_url="https://joined.example/feed",
        homepage_url="https://joined.example",
        source_group="news",
        language_hint="en",
        active=True,
        icon_url="/sources/joined/icon.svg",
        icon_status="resolved",
        icon_updated_at=NOW,
    )
    primary = _media("primary", kind="image", fetch_status="remote_only", alt_text="Article image")
    secondary = _media("secondary", kind="video", fetch_status="fetched")
    db_session.add_all([source, primary, secondary])
    await db_session.flush()
    article = _article(
        title="Composed article",
        summary=None,
        content_text="  First\n line   " + "x" * 700,
        content_html_sanitized="<p>Safe body</p><script>alert('unsafe')</script>",
        source_id=source.id,
        primary_image_id=primary.id,
        language="en",
        direction="ltr",
        topic="AI",
        domain="JOINED.EXAMPLE.",
        score=61,
        legacy_source_name="Wrong legacy source",
    )
    article.authors = ["Reporter"]
    article.tags = ["ai", "news"]
    article.is_rewrite_ready = True
    article.rewrite_ready_reason = "ready"
    article.rewrite_blockers = []
    db_session.add(article)
    await db_session.flush()
    db_session.add_all(
        [
            ItemMedia(
                content_item_id=article.id,
                media_asset_id=primary.id,
                role="primary_image",
                sort_order=0,
                confidence=Decimal("1"),
                extracted_from="feed",
            ),
            ItemMedia(
                content_item_id=article.id,
                media_asset_id=secondary.id,
                role="inline_video",
                sort_order=1,
                confidence=Decimal("0.8"),
                extracted_from="body",
            ),
        ]
    )

    incomplete = _story("Incomplete story")
    complete = _story("Complete story")
    db_session.add_all([incomplete, complete])
    await db_session.flush()
    historical = _story("Historical story", superseded_by_id=complete.id)
    db_session.add(historical)
    await db_session.flush()
    db_session.add_all(
        [
            _evidence(incomplete.id, article.id, "incomplete", "short", "https://one.example/a"),
            _evidence(
                complete.id,
                article.id,
                "complete-primary",
                "a" * 450,
                "https://one.example/b",
                is_primary=True,
            ),
            _evidence(
                complete.id,
                None,
                "complete-second",
                "b" * 450,
                "https://two.example/c",
            ),
            _evidence(historical.id, article.id, "historical", "old", "https://old.example/a"),
        ]
    )
    await db_session.commit()

    summary_response = await _get(db_session, "/articles?limit=10")
    assert summary_response.status_code == 200
    payload = summary_response.json()
    assert payload["result_count"] == 1
    assert payload["next_cursor"] is None
    assert len(payload["items"]) == 1
    summary = payload["items"][0]
    assert set(summary) == {
        "id",
        "title",
        "summary",
        "excerpt",
        "source",
        "canonical_url",
        "published_at",
        "sort_at",
        "display_at",
        "date_basis",
        "score",
        "content_type",
        "topic",
        "domain",
        "language",
        "direction",
        "coverage",
        "image",
        "has_image",
        "saved",
        "saved_collection_ids",
        "article_readiness",
    }
    assert summary["source"] == {
        "id": str(source.id),
        "name": "Joined Wire",
        "platform": "rss",
        "homepage_url": "https://joined.example",
        "icon_url": "/sources/joined/icon.svg",
        "icon_status": "resolved",
        "icon_updated_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    assert summary["domain"] == "joined.example"
    assert summary["summary"] is None
    assert summary["excerpt"].startswith("First line ")
    assert len(summary["excerpt"]) == 500
    assert summary["coverage"]["state"] == "complete"
    assert {story["id"] for story in summary["coverage"]["stories"]} == {
        str(incomplete.id),
        str(complete.id),
    }
    assert summary["image"]["alt_text"] == "Article image"
    assert summary["has_image"] is True
    assert summary["saved"] is False and summary["saved_collection_ids"] == []
    assert summary["article_readiness"] == {"ready": True}
    for forbidden in (
        "content_text",
        "sanitized_html",
        "metrics",
        "classification_metadata",
        "score_breakdown",
        "advanced",
    ):
        assert forbidden not in summary
    assert "unsafe" not in summary_response.text

    detail_response = await _get(db_session, f"/articles/{article.id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert set(detail) == {
        "id",
        "title",
        "summary",
        "excerpt",
        "source",
        "canonical_url",
        "published_at",
        "sort_at",
        "display_at",
        "date_basis",
        "score",
        "content_type",
        "topic",
        "domain",
        "language",
        "direction",
        "coverage",
        "image",
        "has_image",
        "saved",
        "saved_collection_ids",
        "article_readiness",
        "content_text",
        "content_origin",
        "sanitized_html",
        "authors",
        "tags",
        "media",
        "story_links",
        "evidence_references",
        "advanced",
    }
    assert detail["content_text"].startswith("  First\n line")
    assert detail["source"] == summary["source"]
    assert detail["content_origin"] == "unknown"
    assert detail["sanitized_html"] is not None
    assert "<script" not in detail["sanitized_html"]
    assert detail["authors"] == ["Reporter"]
    assert detail["tags"] == ["ai", "news"]
    assert len(detail["media"]) == 2
    assert {item["role"] for item in detail["media"]} == {"primary_image", "inline_video"}
    assert len(detail["story_links"]) == 3
    assert sum(link["active"] for link in detail["story_links"]) == 2
    assert any(link["superseded_by_id"] == str(complete.id) for link in detail["story_links"])
    assert len(detail["evidence_references"]) == 3
    assert all(reference["story_url"].startswith("/stories/") for reference in detail["evidence_references"])
    assert detail["article_readiness"] == {"ready": True, "reason": "ready", "blockers": []}
    assert detail["saved"] is False and detail["saved_collection_ids"] == []
    assert detail["advanced"]["status"] == "new"
    assert detail["advanced"]["raw_classification"] == {
        "content_type": "article",
        "topic": "AI",
        "language": "en",
    }
    assert "metrics" not in detail["advanced"]
    assert "classification_metadata" not in detail["advanced"]
    assert "score_breakdown" not in detail["advanced"]
    assert all(link["research_runs_url"].endswith("/research-runs") for link in detail["story_links"])
    assert all(link["content_packs_url"].endswith("/content-packs") for link in detail["story_links"])


async def test_articles_use_one_canonical_classification_for_output_facets_and_filters(
    db_session: AsyncSession,
):
    article_news = _article(
        title="Generic article news",
        content_type=" Article ",
        topic=" news ",
        language=" EN ",
        sort_at=NOW,
    )
    news_news = _article(
        title="Duplicate news",
        content_type="NEWS",
        topic="News",
        language="en",
        sort_at=NOW - timedelta(minutes=1),
    )
    general = _article(
        title="Generic topic",
        content_type="Tutorial",
        topic=" GENERAL ",
        language="FA",
        direction="rtl",
        sort_at=NOW - timedelta(minutes=2),
    )
    unknown = _article(
        title="Unknown classifications",
        content_type=" Report ",
        topic=" Analysis ",
        language=" ZZ ",
        sort_at=NOW - timedelta(minutes=3),
    )
    nullable = _article(
        title="Nullable classifications",
        content_type="article",
        topic=None,
        language=None,
        sort_at=NOW - timedelta(minutes=4),
    )
    db_session.add_all([article_news, news_news, general, unknown, nullable])
    await db_session.commit()

    facets_response = await _get(db_session, "/articles/facets")
    assert facets_response.status_code == 200
    facets = facets_response.json()
    assert facets["content_types"] == [
        {"value": "article", "count": 1},
        {"value": "news", "count": 2},
        {"value": "report", "count": 1},
        {"value": "tutorial", "count": 1},
    ]
    assert facets["topics"] == [{"value": "analysis", "count": 1}]
    assert facets["languages"] == [
        {"value": "en", "count": 2},
        {"value": "fa", "count": 1},
        {"value": "zz", "count": 1},
    ]

    first_page = await _get(db_session, "/articles?content_type=NEWS&limit=1")
    assert first_page.status_code == 200
    assert first_page.json()["result_count"] == 2
    assert first_page.json()["items"][0]["content_type"] == "news"
    assert first_page.json()["items"][0]["topic"] is None
    cursor = first_page.json()["next_cursor"]
    assert cursor is not None

    second_page = await _get(db_session, f"/articles?content_type=news&limit=1&cursor={cursor}")
    assert second_page.status_code == 200
    assert second_page.json()["result_count"] == 2
    assert second_page.json()["items"][0]["content_type"] == "news"
    assert second_page.json()["items"][0]["topic"] is None
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]

    topic_filter = await _get(db_session, "/articles?topic=ANALYSIS")
    assert topic_filter.status_code == 200
    assert topic_filter.json()["result_count"] == 1
    assert topic_filter.json()["items"][0]["id"] == str(unknown.id)

    language_filter = await _get(db_session, "/articles?language=fa")
    assert language_filter.status_code == 200
    assert language_filter.json()["result_count"] == 1
    assert language_filter.json()["items"][0]["id"] == str(general.id)
    assert language_filter.json()["items"][0]["language"] == "fa"
    assert language_filter.json()["items"][0]["topic"] is None

    detail_response = await _get(db_session, f"/articles/{article_news.id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["content_type"] == "news"
    assert detail["topic"] is None
    assert detail["language"] == "en"
    assert detail["advanced"]["raw_classification"] == {
        "content_type": " Article ",
        "topic": " news ",
        "language": " EN ",
    }

    hidden_generic = await _get(db_session, "/articles?topic=General")
    assert hidden_generic.status_code == 422


async def test_articles_handle_legacy_source_and_missing_optional_fields(db_session: AsyncSession):
    legacy = _article(
        title="خبر فارسی",
        summary="خلاصه",
        content_text="متن",
        published_at=None,
        language="fa",
        direction="rtl",
        topic="Economy",
        domain="News.Example.COM.",
        legacy_source_name="Legacy Wire",
        legacy_source_platform="telegram_public",
    )
    missing = _article(
        title=None,
        summary=None,
        content_text=None,
        published_at=None,
        language="en",
        direction="ltr",
        topic=None,
        domain=None,
        legacy_source_name=None,
        legacy_source_platform=None,
        sort_at=NOW - timedelta(minutes=1),
    )
    db_session.add_all([legacy, missing])
    await db_session.flush()
    incomplete_story = _story("Legacy incomplete")
    db_session.add(incomplete_story)
    await db_session.flush()
    db_session.add(
        _evidence(
            incomplete_story.id,
            legacy.id,
            "legacy-incomplete",
            "short",
            "https://legacy.example/a",
        )
    )
    await db_session.commit()

    response = await _get(db_session, "/articles?limit=10")
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["items"]}
    legacy_row = by_id[str(legacy.id)]
    assert legacy_row["source"] == {
        "id": None,
        "name": "Legacy Wire",
        "platform": "telegram_public",
        "homepage_url": None,
    }
    assert legacy_row["domain"] == "news.example.com"
    assert legacy_row["language"] == "fa"
    assert legacy_row["direction"] == "rtl"
    assert legacy_row["published_at"] is None
    assert legacy_row["display_at"] == legacy_row["sort_at"]
    assert legacy_row["date_basis"] == "collected"
    assert legacy_row["coverage"]["state"] == "incomplete"
    assert [story["id"] for story in legacy_row["coverage"]["stories"]] == [str(incomplete_story.id)]
    assert legacy_row["image"] is None and legacy_row["has_image"] is False

    missing_row = by_id[str(missing.id)]
    assert missing_row["title"] is None
    assert missing_row["summary"] is None
    assert missing_row["excerpt"] is None
    assert missing_row["source"] == {
        "id": None,
        "name": None,
        "platform": None,
        "homepage_url": None,
    }
    assert missing_row["published_at"] is None
    assert missing_row["topic"] is None
    assert missing_row["domain"] is None
    assert missing_row["direction"] == "ltr"
    assert missing_row["coverage"] == {"state": "ungrouped", "stories": []}


async def test_articles_support_single_multi_value_and_cross_field_filters(db_session: AsyncSession):
    source_a = Source(
        platform="rss",
        name="Source A",
        feed_url="https://a.example/feed",
        homepage_url="https://a.example",
        source_group="news",
        active=True,
    )
    source_b = Source(
        platform="telegram_public",
        name="Source B",
        feed_url="https://b.example/feed",
        homepage_url="https://b.example",
        source_group="news",
        active=True,
    )
    db_session.add_all([source_a, source_b])
    await db_session.flush()
    en_ai = _article(title="EN AI", language="en", topic="AI", source_id=source_a.id)
    en_tech = _article(
        title="EN Tech",
        language="en",
        topic="Tech",
        source_id=source_a.id,
        content_type="news",
    )
    en_economy = _article(title="EN Economy", language="en", topic="Economy", source_id=source_b.id)
    fa_ai = _article(
        title="FA AI",
        language="fa",
        direction="rtl",
        topic="AI",
        source_id=source_b.id,
        content_type="report",
    )
    db_session.add_all([en_ai, en_tech, en_economy, fa_ai])
    await db_session.commit()

    single = await _get(db_session, "/articles?language=fa")
    assert single.status_code == 200
    assert single.json()["result_count"] == 1
    assert [item["id"] for item in single.json()["items"]] == [str(fa_ai.id)]

    combined = await _get(db_session, "/articles?language=en&topic=AI&topic=Tech")
    assert combined.status_code == 200
    assert combined.json()["result_count"] == 2
    assert {item["id"] for item in combined.json()["items"]} == {str(en_ai.id), str(en_tech.id)}

    source_and_type = await _get(
        db_session,
        f"/articles?source_id={source_a.id}&content_type=news",
    )
    assert source_and_type.status_code == 200
    assert source_and_type.json()["result_count"] == 1
    assert source_and_type.json()["items"][0]["id"] == str(en_tech.id)


async def test_articles_filter_score_date_and_usable_image_bounds(db_session: AsyncSession):
    usable = _media("filter-usable", kind="image", fetch_status="remote_only")
    expired = _media("filter-expired", kind="image", fetch_status="expired")
    db_session.add_all([usable, expired])
    await db_session.flush()
    eligible = _article(title="Eligible", score=25, primary_image_id=usable.id)
    low_score = _article(title="Low", score=10, primary_image_id=usable.id)
    late = _article(
        title="Late",
        score=25,
        primary_image_id=usable.id,
        published_at=NOW + timedelta(days=2),
        sort_at=NOW + timedelta(days=2),
    )
    expired_image = _article(title="Expired", score=25, primary_image_id=expired.id)
    no_image = _article(title="No image", score=25)
    db_session.add_all([eligible, low_score, late, expired_image, no_image])
    await db_session.commit()

    bounded = await _get(
        db_session,
        "/articles?score_min=20&score_max=30"
        "&date_from=2026-07-21T07:00:00Z&date_to=2026-07-21T09:00:00Z"
        "&has_image=true",
    )
    assert bounded.status_code == 200
    assert bounded.json()["result_count"] == 1
    assert bounded.json()["items"][0]["id"] == str(eligible.id)

    without_usable_image = await _get(db_session, "/articles?has_image=false")
    assert without_usable_image.status_code == 200
    assert without_usable_image.json()["result_count"] == 2
    assert {item["id"] for item in without_usable_image.json()["items"]} == {
        str(expired_image.id),
        str(no_image.id),
    }

    invalid_score = await _get(db_session, "/articles?score_min=30&score_max=20")
    invalid_date = await _get(
        db_session,
        "/articles?date_from=2026-07-22T00:00:00Z&date_to=2026-07-21T00:00:00Z",
    )
    assert invalid_score.status_code == 422
    assert invalid_date.status_code == 422


async def test_articles_filter_all_coverage_states(db_session: AsyncSession):
    ungrouped = _article(title="Ungrouped")
    incomplete_item = _article(title="Incomplete")
    complete_item = _article(title="Complete")
    db_session.add_all([ungrouped, incomplete_item, complete_item])
    await db_session.flush()
    incomplete_story = _story("Incomplete")
    complete_story = _story("Complete")
    db_session.add_all([incomplete_story, complete_story])
    await db_session.flush()
    db_session.add_all(
        [
            _evidence(
                incomplete_story.id,
                incomplete_item.id,
                "coverage-incomplete",
                "short",
                "https://one.example/incomplete",
            ),
            _evidence(
                complete_story.id,
                complete_item.id,
                "coverage-complete-primary",
                "a" * 450,
                "https://one.example/complete",
                is_primary=True,
            ),
            _evidence(
                complete_story.id,
                None,
                "coverage-complete-second",
                "b" * 450,
                "https://two.example/complete",
            ),
        ]
    )
    await db_session.commit()

    complete = await _get(db_session, "/articles?coverage=complete")
    assert complete.status_code == 200
    assert complete.json()["result_count"] == 1
    assert complete.json()["items"][0]["id"] == str(complete_item.id)

    incomplete_or_ungrouped = await _get(
        db_session,
        "/articles?coverage=incomplete&coverage=ungrouped",
    )
    assert incomplete_or_ungrouped.status_code == 200
    assert incomplete_or_ungrouped.json()["result_count"] == 2
    assert {item["id"] for item in incomplete_or_ungrouped.json()["items"]} == {
        str(incomplete_item.id),
        str(ungrouped.id),
    }


async def test_coverage_filter_facets_and_item_payload_share_the_python_completeness_rule(
    db_session: AsyncSession,
):
    """The SQL coverage rule must not re-derive source identity or the primary flag.

    Before the persisted identity/primary columns, ``subdomains`` counted as two
    independent sources in SQL and one in Python, and a truthy non-``true``
    ``is_primary`` value was primary in Python and not in SQL. Both stories below
    therefore had a coverage filter and a facet count that contradicted the
    ``coverage.state`` returned on the item itself.
    """

    subdomains_item = _article(title="Same registrable domain")
    truthy_primary_item = _article(title="Truthy primary flag")
    db_session.add_all([subdomains_item, truthy_primary_item])
    await db_session.flush()
    subdomains_story = _story("Same registrable domain")
    truthy_primary_story = _story("Truthy primary flag")
    db_session.add_all([subdomains_story, truthy_primary_story])
    await db_session.flush()
    db_session.add_all(
        [
            _evidence(
                subdomains_story.id,
                subdomains_item.id,
                "identity-a",
                "a" * 450,
                "https://a.example.com/one",
                is_primary=True,
            ),
            _evidence(
                subdomains_story.id,
                None,
                "identity-b",
                "b" * 450,
                "https://b.example.com/two",
            ),
            _evidence(
                truthy_primary_story.id,
                truthy_primary_item.id,
                "primary-a",
                "a" * 450,
                "https://one.example/primary",
                snapshot_metadata={"is_primary": "yes"},
            ),
            _evidence(
                truthy_primary_story.id,
                None,
                "primary-b",
                "b" * 450,
                "https://two.example/primary",
            ),
        ]
    )
    await db_session.commit()

    listed = await _get(db_session, "/articles")
    assert listed.status_code == 200
    states = {item["title"]: item["coverage"]["state"] for item in listed.json()["items"]}
    assert states == {
        "Same registrable domain": "incomplete",
        "Truthy primary flag": "complete",
    }

    complete = await _get(db_session, "/articles?coverage=complete")
    assert complete.status_code == 200
    assert [item["id"] for item in complete.json()["items"]] == [str(truthy_primary_item.id)]

    incomplete = await _get(db_session, "/articles?coverage=incomplete")
    assert incomplete.status_code == 200
    assert [item["id"] for item in incomplete.json()["items"]] == [str(subdomains_item.id)]

    facets = await _get(db_session, "/articles/facets")
    assert facets.status_code == 200
    assert facets.json()["coverage"] == [
        {"value": "complete", "count": 1},
        {"value": "incomplete", "count": 1},
    ]


async def test_filtered_cursor_is_stable_and_rejected_after_filter_change(db_session: AsyncSession):
    english = [
        _article(
            title=f"English {index}",
            language="en",
            published_at=None,
            sort_at=NOW - timedelta(minutes=index),
        )
        for index in range(3)
    ]
    persian = _article(
        title="Persian",
        language="fa",
        direction="rtl",
        published_at=None,
        sort_at=NOW + timedelta(minutes=1),
    )
    db_session.add_all([*english, persian])
    await db_session.commit()

    first = await _get(db_session, "/articles?language=en&limit=1")
    assert first.status_code == 200
    assert first.json()["result_count"] == 3
    cursor = first.json()["next_cursor"]
    second = await _get(db_session, f"/articles?language=en&limit=1&cursor={cursor}")
    assert second.status_code == 200
    assert second.json()["result_count"] == 3
    assert first.json()["items"][0]["id"] == str(english[0].id)
    assert second.json()["items"][0]["id"] == str(english[1].id)

    changed_filter = await _get(db_session, f"/articles?language=fa&cursor={cursor}")
    assert changed_filter.status_code == 422
    assert changed_filter.json()["detail"] == "invalid article cursor"


async def test_articles_search_title_and_body_with_exact_count_filters_and_cursor_binding(
    db_session: AsyncSession,
):
    climate = _article(
        title="Climate Outlook",
        content_text="Body without the searched phrase.",
        language="en",
        score=80,
        sort_at=NOW,
    )
    second_report = _article(
        title="Climate Report Follow-up",
        language="en",
        score=40,
        sort_at=NOW - timedelta(minutes=1),
    )
    body_only = _article(
        title="Unrelated headline",
        content_text="Climate Outlook appears only in the body.",
        language="en",
        score=90,
        sort_at=NOW + timedelta(minutes=1),
    )
    persian = _article(
        title="گزارش فناوری امروز",
        language="fa",
        direction="rtl",
        sort_at=NOW - timedelta(minutes=2),
    )
    literal_wildcard = _article(title="Budget reached 100%", language="en")
    db_session.add_all([climate, second_report, body_only, persian, literal_wildcard])
    await db_session.commit()

    filtered = await _get(db_session, "/articles?q=%20CLIMATE%20&language=en&sort=score")
    assert filtered.status_code == 200
    assert filtered.json()["result_count"] == 3
    assert [item["id"] for item in filtered.json()["items"]] == [
        str(body_only.id),
        str(climate.id),
        str(second_report.id),
    ]

    persian_result = await _get(db_session, "/articles?q=گزارش%20فناوری")
    assert persian_result.status_code == 200
    assert persian_result.json()["result_count"] == 1
    assert persian_result.json()["items"][0]["id"] == str(persian.id)

    literal_result = await _get(db_session, "/articles?q=%25")
    assert literal_result.status_code == 200
    assert literal_result.json()["result_count"] == 1
    assert literal_result.json()["items"][0]["id"] == str(literal_wildcard.id)

    first = await _get(db_session, "/articles?q=climate&limit=1")
    cursor = first.json()["next_cursor"]
    assert cursor
    second = await _get(db_session, f"/articles?q=CLIMATE&limit=1&cursor={cursor}")
    assert second.status_code == 200
    assert second.json()["result_count"] == 3

    changed_query = await _get(db_session, f"/articles?q=outlook&cursor={cursor}")
    assert changed_query.status_code == 422
    assert changed_query.json()["detail"] == "invalid article cursor"


async def test_article_facets_return_persisted_values_and_exact_counts(db_session: AsyncSession):
    source_a = Source(
        platform="rss",
        name="Alpha Wire",
        feed_url="https://alpha.example/feed",
        homepage_url="https://alpha.example",
        source_group="news",
        active=True,
    )
    source_b = Source(
        platform="telegram_public",
        name="Beta Wire",
        feed_url="https://beta.example/feed",
        homepage_url="https://beta.example",
        source_group="news",
        active=True,
    )
    db_session.add_all([source_a, source_b])
    await db_session.flush()
    en_ai = _article(
        title="English AI",
        language="en",
        topic="AI",
        content_type="news",
        source_id=source_a.id,
    )
    en_tech = _article(
        title="English Tech",
        language="en",
        topic="Tech",
        content_type="news",
        source_id=source_a.id,
    )
    fa_ai = _article(
        title="Persian AI",
        language="fa",
        direction="rtl",
        topic="AI",
        content_type="article",
        source_id=source_b.id,
    )
    db_session.add_all([en_ai, en_tech, fa_ai])
    await db_session.flush()
    incomplete_story = _story("Facet incomplete")
    complete_story = _story("Facet complete")
    db_session.add_all([incomplete_story, complete_story])
    await db_session.flush()
    db_session.add_all(
        [
            _evidence(
                incomplete_story.id,
                en_ai.id,
                "facet-incomplete",
                "short",
                "https://one.example/facet-incomplete",
            ),
            _evidence(
                complete_story.id,
                fa_ai.id,
                "facet-complete-primary",
                "a" * 450,
                "https://one.example/facet-complete",
                is_primary=True,
            ),
            _evidence(
                complete_story.id,
                None,
                "facet-complete-second",
                "b" * 450,
                "https://two.example/facet-complete",
            ),
        ]
    )
    await db_session.commit()

    response = await _get(db_session, "/articles/facets")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"languages", "topics", "content_types", "sources", "coverage"}
    assert payload["languages"] == [{"value": "en", "count": 2}, {"value": "fa", "count": 1}]
    assert payload["topics"] == [{"value": "AI", "count": 2}, {"value": "Tech", "count": 1}]
    assert payload["content_types"] == [
        {"value": "article", "count": 1},
        {"value": "news", "count": 2},
    ]
    assert payload["sources"] == [
        {"id": str(source_a.id), "name": "Alpha Wire", "platform": "rss", "count": 2},
        {
            "id": str(source_b.id),
            "name": "Beta Wire",
            "platform": "telegram_public",
            "count": 1,
        },
    ]
    assert payload["coverage"] == [
        {"value": "complete", "count": 1},
        {"value": "incomplete", "count": 1},
        {"value": "ungrouped", "count": 1},
    ]


async def test_newest_cursor_is_stable_when_newer_article_is_inserted(db_session: AsyncSession):
    original = [
        _article(
            title=f"Original {index}",
            published_at=None,
            sort_at=NOW - timedelta(minutes=index),
        )
        for index in range(3)
    ]
    db_session.add_all(original)
    await db_session.commit()

    first = await _get(db_session, "/articles?sort=newest&limit=1")
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor
    inserted = _article(
        title="Inserted newer",
        published_at=None,
        sort_at=NOW + timedelta(minutes=1),
    )
    db_session.add(inserted)
    await db_session.commit()

    second = await _get(db_session, f"/articles?sort=newest&limit=2&cursor={cursor}")
    assert second.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [str(original[0].id)]
    assert [item["id"] for item in second.json()["items"]] == [
        str(original[1].id),
        str(original[2].id),
    ]
    assert str(inserted.id) not in {item["id"] for item in second.json()["items"]}


async def test_score_cursor_is_stable_and_bound_to_sort(db_session: AsyncSession):
    original = [
        _article(title="Score 30", score=30, sort_at=NOW),
        _article(title="Score 20", score=20, sort_at=NOW + timedelta(minutes=2)),
        _article(title="Score 10", score=10, sort_at=NOW + timedelta(minutes=3)),
    ]
    db_session.add_all(original)
    await db_session.commit()

    first = await _get(db_session, "/articles?sort=score&limit=1")
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    inserted = _article(title="Inserted high score", score=40, sort_at=NOW + timedelta(minutes=4))
    db_session.add(inserted)
    await db_session.commit()

    second = await _get(db_session, f"/articles?sort=score&limit=2&cursor={cursor}")
    assert second.status_code == 200
    assert [item["score"] for item in second.json()["items"]] == [20, 10]
    assert str(inserted.id) not in {item["id"] for item in second.json()["items"]}

    wrong_sort = await _get(db_session, f"/articles?sort=newest&cursor={cursor}")
    assert wrong_sort.status_code == 422
    assert wrong_sort.json()["detail"] == "invalid article cursor"


async def test_score_cursor_is_stable_when_all_sort_keys_tie(db_session: AsyncSession):
    ids = [
        UUID("00000000-0000-4000-8000-000000000003"),
        UUID("00000000-0000-4000-8000-000000000002"),
        UUID("00000000-0000-4000-8000-000000000001"),
    ]
    rows = [_article(title=f"Tied {index}", score=20, sort_at=NOW) for index in range(3)]
    for row, content_item_id in zip(rows, ids, strict=True):
        row.id = content_item_id
    db_session.add_all(rows)
    await db_session.commit()

    first = await _get(db_session, "/articles?sort=score&limit=1")
    cursor = first.json()["next_cursor"]
    assert [item["id"] for item in first.json()["items"]] == [str(ids[0])]

    inserted = _article(title="New tied row", score=20, sort_at=NOW)
    inserted.id = UUID("00000000-0000-4000-8000-000000000004")
    db_session.add(inserted)
    await db_session.commit()

    second = await _get(db_session, f"/articles?sort=score&limit=2&cursor={cursor}")
    assert [item["id"] for item in second.json()["items"]] == [str(ids[1]), str(ids[2])]


async def test_articles_reject_invalid_cursor_and_return_404_for_unknown_id(db_session: AsyncSession):
    invalid = await _get(db_session, "/articles?cursor=not-a-cursor")
    missing = await _get(db_session, f"/articles/{uuid4()}")

    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid article cursor"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "article not found"


def test_article_cursor_is_deterministic_and_routes_are_read_only():
    from types import SimpleNamespace

    from app.api.articles import decode_article_cursor, encode_article_cursor

    row = SimpleNamespace(id=UUID("00000000-0000-4000-8000-000000000001"), display_at=NOW, score=42)
    newest = encode_article_cursor("newest", row)
    score = encode_article_cursor("score", row)
    assert newest == encode_article_cursor("newest", row)
    assert score == encode_article_cursor("score", row)
    assert decode_article_cursor(newest, "newest") == (NOW, row.id)
    assert decode_article_cursor(score, "score") == (42, NOW, row.id)

    operations = {
        (path, method.upper())
        for path, definition in app.openapi()["paths"].items()
        for method in definition
        if path.startswith("/articles")
    }
    assert operations == {
        ("/articles", "GET"),
        ("/articles/facets", "GET"),
        ("/articles/{content_item_id}", "GET"),
    }


async def _get(session: AsyncSession, path: str):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


def _article(
    *,
    title: str | None,
    summary: str | None = "Summary",
    content_text: str | None = "Body",
    content_html_sanitized: str | None = "<p>Body</p>",
    source_id: UUID | None = None,
    primary_image_id: UUID | None = None,
    published_at: datetime | None = NOW,
    sort_at: datetime = NOW,
    language: str | None = "en",
    direction: str | None = "ltr",
    topic: str | None = "AI",
    domain: str | None = "example.com",
    score: int = 10,
    content_type: str = "article",
    legacy_source_name: str | None = "Legacy source",
    legacy_source_platform: str | None = "rss",
) -> ContentItem:
    metrics = {"classification": {"category": topic}} if topic is not None else {}
    metadata = {}
    if domain is not None:
        metadata["source_domain"] = domain
    if legacy_source_name is not None:
        metadata["source_name"] = legacy_source_name
    if legacy_source_platform is not None:
        metadata["source_platform"] = legacy_source_platform
    return ContentItem(
        item_type="article",
        canonical_url="https://example.com/article",
        title=title,
        summary=summary,
        content_text=content_text,
        content_html_sanitized=content_html_sanitized,
        language_code=language,
        script_code="Arab" if direction == "rtl" else "Latn",
        direction=direction,
        authors=[],
        tags=[],
        published_at=published_at,
        sort_at=sort_at,
        date_source="source" if published_at else "collected",
        date_parse_status="parsed" if published_at else "missing",
        primary_source_id=source_id,
        primary_image_id=primary_image_id,
        status="new",
        score=score,
        metrics=metrics,
        content_type=content_type,
        content_type_confidence=Decimal("1"),
        classification_reasons=["test classification"],
        classification_metadata=metadata,
        rewrite_bucket="technical_article",
        freshness_bucket="fresh",
        source_tier="A",
        quality_status="needs_review",
        is_rewrite_ready=False,
        rewrite_ready_reason="missing evidence",
        rewrite_blockers=["missing_evidence"],
        score_breakdown={},
        ranking_metadata={},
        title_quality="meaningful",
        title_was_generated=False,
        content_intent=None,
    )


def _media(
    suffix: str,
    *,
    kind: str,
    fetch_status: str,
    alt_text: str | None = None,
) -> MediaAsset:
    return MediaAsset(
        original_url=f"https://media.example/{suffix}",
        normalized_url=f"https://media.example/{suffix}",
        url_hash=f"hash-{suffix}",
        kind=kind,
        mime_type="image/jpeg" if kind == "image" else "video/mp4",
        width=1200,
        height=675,
        alt_text=alt_text,
        title=f"Media {suffix}",
        source_field="body",
        fetch_status=fetch_status,
        media_quality="good",
        media_confidence=Decimal("1"),
        is_primary_candidate=kind == "image",
        is_primary=kind == "image",
        media_source_type="external",
        asset_role="inline_image" if kind == "image" else "inline_video",
        raw_metadata={},
    )


def _story(title: str, *, superseded_by_id: UUID | None = None) -> Story:
    return Story(
        title=title,
        status="inbox",
        primary_language="en",
        superseded_by_id=superseded_by_id,
    )


def _evidence(
    story_id: UUID,
    content_item_id: UUID | None,
    suffix: str,
    content_text: str,
    source_url: str,
    *,
    is_primary: bool = False,
    snapshot_metadata: dict | None = None,
) -> StoryEvidenceSnapshot:
    return StoryEvidenceSnapshot(
        story_id=story_id,
        content_item_id=content_item_id,
        evidence_key=f"url:{suffix}:{'a' * 64}",
        source_url=source_url,
        title=f"Evidence {suffix}",
        content_text=content_text,
        authors=["Reporter"],
        published_at=NOW,
        content_sha256=(suffix.encode().hex() + "0" * 64)[:64],
        snapshot_metadata={"is_primary": is_primary} if snapshot_metadata is None else snapshot_metadata,
    )
