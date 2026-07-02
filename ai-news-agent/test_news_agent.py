import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("NEWS_DB_PATH")
        os.environ["NEWS_DB_PATH"] = os.path.join(self.tmp.name, "news.db")

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("NEWS_DB_PATH", None)
        else:
            os.environ["NEWS_DB_PATH"] = self.old_db
        self.tmp.cleanup()

    def test_save_get_and_update_articles(self):
        from storage import get_articles, init_db, save_articles, update_article_status

        init_db()
        article = {
            "source": "Test",
            "title": "OpenAI ships a model",
            "url": "https://example.com/story",
            "published_at": "2026-07-02T00:00:00Z",
            "summary": "A useful summary",
            "category": "AI",
            "score": 3,
        }

        self.assertEqual(save_articles([article, article]), 1)
        rows = get_articles()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "new")
        self.assertEqual(rows[0]["url"], article["url"])

        update_article_status(rows[0]["id"], "approved")
        self.assertEqual(get_articles()[0]["status"], "approved")

    def test_get_articles_filters_by_date_category_status_and_clear(self):
        from storage import clear_articles, get_articles, init_db, save_articles

        init_db()
        save_articles(
            [
                {
                    "source": "Test",
                    "title": "AI today",
                    "url": "https://example.com/today",
                    "published_at": "2026-07-02T10:30:00",
                    "summary": "OpenAI model",
                    "category": "AI",
                    "score": 3,
                },
                {
                    "source": "Test",
                    "title": "Tech yesterday",
                    "url": "https://example.com/yesterday",
                    "published_at": "2026-07-01T10:30:00",
                    "summary": "GitHub API",
                    "category": "Tech",
                    "score": 2,
                },
            ]
        )

        rows = get_articles(start_date=date(2026, 7, 2), end_date=date(2026, 7, 2), category="AI", status="new")
        self.assertEqual([row["url"] for row in rows], ["https://example.com/today"])

        clear_articles()
        self.assertEqual(get_articles(), [])


class DateUtilTests(unittest.TestCase):
    def test_parse_range_and_normalize_dates(self):
        from utils import is_within_date_range, normalize_date_for_storage, parse_article_date

        parsed = parse_article_date("Thu, 02 Jul 2026 10:30:00 GMT")
        self.assertEqual(parsed.date(), date(2026, 7, 2))
        self.assertEqual(parse_article_date(1782988200).date(), date(2026, 7, 2))
        self.assertEqual(parse_article_date((2026, 7, 2, 10, 30, 0, 0, 0, 0)).date(), date(2026, 7, 2))
        self.assertIsNone(parse_article_date("not a date"))
        self.assertTrue(is_within_date_range(parsed, date(2026, 7, 2), date(2026, 7, 2)))
        self.assertFalse(is_within_date_range(parsed, date(2026, 7, 3), date(2026, 7, 4)))
        self.assertEqual(normalize_date_for_storage(parsed), "2026-07-02T10:30:00")


class ConnectorTests(unittest.TestCase):
    def test_rss_skips_bad_entries(self):
        from connectors import fetch_rss_articles

        entry = {
            "title": "AI story",
            "link": "https://example.com/ai",
            "published": "Thu, 02 Jul 2026 00:00:00 GMT",
            "summary": "<p>Hello</p>",
        }
        with patch("connectors.RSS_FEEDS", ["https://example.com/feed"]), patch("connectors.feedparser.parse") as parse:
            parse.return_value = Mock(feed=Mock(get=lambda key, default=None: "Feed"), entries=[entry, {"title": ""}])

            articles = fetch_rss_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "Feed")
        self.assertEqual(articles[0]["url"], entry["link"])

    def test_rss_filters_selected_date_range_and_missing_dates(self):
        from connectors import fetch_rss_articles

        entries = [
            {"title": "Fresh AI", "link": "https://example.com/fresh", "published": "Thu, 02 Jul 2026 00:00:00 GMT"},
            {"title": "Old AI", "link": "https://example.com/old", "published": "Tue, 30 Jun 2026 00:00:00 GMT"},
            {"title": "No Date AI", "link": "https://example.com/no-date"},
        ]
        with patch("connectors.RSS_FEEDS", ["https://example.com/feed"]), patch("connectors.feedparser.parse") as parse:
            parse.return_value = Mock(feed=Mock(get=lambda key, default=None: "Feed"), entries=entries)

            articles = fetch_rss_articles(start_date=date(2026, 7, 1), end_date=date(2026, 7, 2))

        self.assertEqual([article["url"] for article in articles], ["https://example.com/fresh"])

    def test_hacker_news_keeps_stories_with_title_and_url(self):
        from connectors import fetch_hacker_news

        def fake_get(url, timeout):
            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = [1, 2] if url.endswith("topstories.json") else {
                "title": "Developer tool",
                "url": "https://example.com/dev",
                "time": 1782950400,
                "text": "summary",
            }
            return response

        with patch("connectors.requests.get", side_effect=fake_get):
            articles = fetch_hacker_news(limit=1)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "Hacker News")
        self.assertEqual(articles[0]["url"], "https://example.com/dev")

    def test_hacker_news_filters_selected_date_range(self):
        from connectors import fetch_hacker_news

        def fake_get(url, timeout):
            response = Mock()
            response.raise_for_status.return_value = None
            if url.endswith("topstories.json"):
                response.json.return_value = [1, 2]
            elif url.endswith("/1.json"):
                response.json.return_value = {"title": "Fresh AI", "url": "https://example.com/fresh", "time": 1782950400}
            else:
                response.json.return_value = {"title": "Old AI", "url": "https://example.com/old", "time": 1782777600}
            return response

        with patch("connectors.requests.get", side_effect=fake_get):
            articles = fetch_hacker_news(limit=2, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))

        self.assertEqual([article["url"] for article in articles], ["https://example.com/fresh"])

    def test_arxiv_reads_atom_entries(self):
        from connectors import fetch_arxiv_ai

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Machine Learning Paper</title>
            <id>https://arxiv.org/abs/1234.5678</id>
            <published>2026-07-02T00:00:00Z</published>
            <summary>Paper summary</summary>
          </entry>
        </feed>"""
        response = Mock(text=xml)
        response.raise_for_status.return_value = None

        with patch("connectors.requests.get", return_value=response):
            articles = fetch_arxiv_ai(limit=1)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "arXiv")
        self.assertEqual(articles[0]["url"], "https://arxiv.org/abs/1234.5678")

    def test_arxiv_filters_selected_date_range(self):
        from connectors import fetch_arxiv_ai

        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Fresh Machine Learning Paper</title>
            <id>https://arxiv.org/abs/fresh</id>
            <published>2026-07-02T00:00:00Z</published>
            <summary>Paper summary</summary>
          </entry>
          <entry>
            <title>Old Machine Learning Paper</title>
            <id>https://arxiv.org/abs/old</id>
            <published>2026-06-30T00:00:00Z</published>
            <summary>Paper summary</summary>
          </entry>
        </feed>"""
        response = Mock(text=xml)
        response.raise_for_status.return_value = None

        with patch("connectors.requests.get", return_value=response):
            articles = fetch_arxiv_ai(limit=2, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))

        self.assertEqual([article["url"] for article in articles], ["https://arxiv.org/abs/fresh"])


class RankerTests(unittest.TestCase):
    def test_classifies_ai_tech_and_general(self):
        from ranker import classify_and_score

        ai = classify_and_score({"title": "OpenAI releases multimodal model", "summary": "LLM agent"})
        tech = classify_and_score({"title": "GitHub cloud API security update", "summary": "developer software"})
        general = classify_and_score({"title": "Local sports recap", "summary": "nothing relevant"})

        self.assertEqual(ai["category"], "AI")
        self.assertGreater(ai["score"], 0)
        self.assertEqual(tech["category"], "Tech")
        self.assertGreater(tech["score"], 0)
        self.assertEqual(general["category"], "General")
        self.assertEqual(general["score"], 0)


class AgentTests(unittest.TestCase):
    def test_run_news_agent_saves_scored_articles_and_ignores_failed_source(self):
        from agent import run_news_agent

        rss_article = {
            "source": "RSS",
            "title": "OpenAI model update",
            "url": "https://example.com/ai",
            "summary": "LLM news",
        }
        irrelevant = {
            "source": "HN",
            "title": "Gardening notes",
            "url": "https://example.com/garden",
            "summary": "No match",
        }

        with patch("agent.init_db") as init_db, patch("agent.save_articles", return_value=1) as save_articles, patch(
            "agent.fetch_rss_articles", return_value=[rss_article]
        ), patch("agent.fetch_hacker_news", return_value=[irrelevant]), patch(
            "agent.fetch_arxiv_ai", side_effect=RuntimeError("down")
        ):
            articles = run_news_agent()

        init_db.assert_called_once()
        save_articles.assert_called_once()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["category"], "AI")
        self.assertGreater(articles[0]["score"], 0)

    def test_run_news_agent_passes_and_enforces_date_range(self):
        from agent import run_news_agent

        fresh = {
            "source": "RSS",
            "title": "OpenAI model update",
            "url": "https://example.com/fresh",
            "published_at": "2026-07-02T10:30:00",
            "summary": "LLM news",
        }
        old = {
            "source": "RSS",
            "title": "OpenAI old model",
            "url": "https://example.com/old",
            "published_at": "2026-06-30T10:30:00",
            "summary": "LLM news",
        }
        undated = {"source": "RSS", "title": "OpenAI no date", "url": "https://example.com/no-date", "summary": "LLM"}

        with patch("agent.init_db"), patch("agent.save_articles", return_value=1) as save_articles, patch(
            "agent.fetch_rss_articles", return_value=[fresh, old, undated]
        ) as rss, patch("agent.fetch_hacker_news", return_value=[]) as hn, patch("agent.fetch_arxiv_ai", return_value=[]) as arxiv:
            articles = run_news_agent(start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))

        rss.assert_called_once_with(start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))
        hn.assert_called_once_with(limit=30, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))
        arxiv.assert_called_once_with(limit=20, start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))
        save_articles.assert_called_once()
        self.assertEqual([article["url"] for article in articles], ["https://example.com/fresh"])
        self.assertEqual(articles[0]["published_at"], "2026-07-02T10:30:00")


class AppHelperTests(unittest.TestCase):
    def test_filter_articles_and_summary_preview(self):
        from app import filter_articles, summary_preview

        articles = [
            {"category": "AI", "status": "new", "summary": "a" * 600},
            {"category": "Tech", "status": "approved", "summary": "short"},
        ]

        self.assertEqual(len(filter_articles(articles, "AI", "All")), 1)
        self.assertEqual(len(filter_articles(articles, "All", "approved")), 1)
        self.assertEqual(len(summary_preview(articles[0]["summary"])), 500)


if __name__ == "__main__":
    unittest.main()
