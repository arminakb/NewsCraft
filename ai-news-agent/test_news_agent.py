import os
import tempfile
import unittest
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
