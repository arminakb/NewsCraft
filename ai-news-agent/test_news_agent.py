import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
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

    def test_storage_keeps_source_type_metrics_group_and_sorting(self):
        from storage import get_articles, init_db, save_articles

        init_db()
        save_articles(
            [
                {
                    "source": "GitHub",
                    "source_type": "github",
                    "title": "owner/repo",
                    "url": "https://github.com/owner/repo",
                    "published_at": "2026-07-02T10:30:00",
                    "summary": "AI agent repo",
                    "category": "Tool",
                    "score": 10,
                    "metrics": {"stars": 100, "forks": 5},
                    "thumbnail_url": "https://example.com/thumb.png",
                    "connector": "github",
                    "source_group": "developer_trends",
                },
                {
                    "source": "arXiv",
                    "source_type": "arxiv",
                    "title": "paper",
                    "url": "https://arxiv.org/abs/1",
                    "published_at": "2026-07-02T12:30:00",
                    "summary": "AI paper",
                    "category": "Research",
                    "score": 1,
                }
            ]
        )

        rows = get_articles(sort_by="Latest first")
        self.assertEqual(rows[0]["source_type"], "arxiv")
        github = get_articles(source_type="github")[0]
        self.assertEqual(github["metrics"]["stars"], 100)
        self.assertEqual(github["thumbnail_url"], "https://example.com/thumb.png")
        self.assertEqual(github["connector"], "github")
        self.assertEqual(github["source_group"], "developer_trends")

    def test_search_sessions_filter_current_results_and_structured_summary(self):
        from storage import create_search_session, get_articles, init_db, save_articles

        init_db()
        first = create_search_session(date(2026, 7, 1), date(2026, 7, 1), ["github"])
        second = create_search_session(date(2026, 7, 2), date(2026, 7, 2), ["huggingface"])
        save_articles(
            [
                {
                    "source": "GitHub",
                    "source_type": "github",
                    "title": "owner/repo",
                    "url": "https://github.com/owner/repo",
                    "published_at": "2026-07-01T10:30:00",
                    "summary": "repo",
                    "category": "Tool",
                    "score": 5,
                    "search_session_id": first,
                    "structured_summary": {"what_it_is": "A repo"},
                },
                {
                    "source": "Hugging Face",
                    "source_type": "huggingface",
                    "title": "org/model",
                    "url": "https://huggingface.co/org/model",
                    "published_at": "2026-07-02T10:30:00",
                    "summary": "model",
                    "category": "Model",
                    "score": 4,
                    "search_session_id": second,
                    "structured_summary": {"what_it_is": "A model"},
                },
            ]
        )

        rows = get_articles(search_session_id=second)
        self.assertEqual([row["url"] for row in rows], ["https://huggingface.co/org/model"])
        self.assertEqual(rows[0]["structured_summary"]["what_it_is"], "A model")


class PaperAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("PAPER_ASSETS_DB_PATH")
        os.environ["PAPER_ASSETS_DB_PATH"] = os.path.join(self.tmp.name, "paper_assets.db")

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("PAPER_ASSETS_DB_PATH", None)
        else:
            os.environ["PAPER_ASSETS_DB_PATH"] = self.old_db
        self.tmp.cleanup()

    def test_arxiv_id_pdf_url_and_existing_pdf_reuse(self):
        from paper_fetcher import build_arxiv_pdf_url, download_arxiv_pdf, extract_arxiv_id

        self.assertEqual(extract_arxiv_id("https://arxiv.org/abs/2602.12345"), "2602.12345")
        self.assertEqual(extract_arxiv_id("https://arxiv.org/pdf/2602.12345"), "2602.12345")
        self.assertEqual(extract_arxiv_id("2602.12345v1"), "2602.12345v1")
        self.assertEqual(build_arxiv_pdf_url("2602.12345v1"), "https://arxiv.org/pdf/2602.12345v1")

        existing_dir = os.path.join(self.tmp.name, "papers", "2602.12345")
        os.makedirs(existing_dir)
        existing_pdf = os.path.join(existing_dir, "paper.pdf")
        with open(existing_pdf, "wb") as handle:
            handle.write(b"%PDF-1.4")

        self.assertEqual(download_arxiv_pdf("2602.12345", output_dir=os.path.join(self.tmp.name, "papers")), existing_pdf)
        with self.assertRaises(ValueError):
            extract_arxiv_id("https://example.com/not-arxiv")

    def test_clean_sections_brief_and_storage(self):
        from paper_extractor import clean_paper_text, extract_basic_sections
        from paper_storage import get_paper_asset, init_paper_assets_db, list_paper_assets, save_paper_asset
        from research_brief import generate_research_brief, write_markdown_assets

        raw_text = """
        Abstract
        This paper studies reliable AI agents.
        Introduction
        Current agents fail silently in production.
        Method
        We add lightweight checks around tool calls.
        Results
        The checks catch common failures.
        References
        [1] A citation
        """
        clean_text = clean_paper_text(raw_text)
        self.assertNotIn("References", clean_text)
        sections = extract_basic_sections(clean_text)
        self.assertIn("Abstract", sections)
        self.assertIn("Method", sections)

        article = {
            "id": 42,
            "title": "Reliable AI Agents",
            "url": "https://arxiv.org/abs/2602.12345",
            "summary": "Short abstract",
            "metrics": {"authors": ["Ada Lovelace"]},
        }
        brief = generate_research_brief(article, clean_text, sections)
        self.assertIn("Reliable AI Agents", brief["one_line_summary"])
        self.assertTrue(brief["key_findings"])

        paths = write_markdown_assets(article, brief, self.tmp.name, "paper.pdf")
        self.assertTrue(os.path.exists(paths["research_brief_path"]))
        self.assertTrue(os.path.exists(paths["instagram_brief_path"]))
        self.assertTrue(os.path.exists(paths["podcast_brief_path"]))

        init_paper_assets_db()
        save_paper_asset(
            {
                "arxiv_id": "2602.12345",
                "article_id": 42,
                "title": "Reliable AI Agents",
                "authors": ["Ada Lovelace"],
                "abstract": "Short abstract",
                "pdf_url": "https://arxiv.org/pdf/2602.12345",
                "local_pdf_path": "paper.pdf",
                "full_text_path": "full_text.txt",
                "sections": sections,
                **paths,
                "status": "ready",
            }
        )
        save_paper_asset({"arxiv_id": "2602.12345", "title": "Updated title", "status": "ready"})
        self.assertEqual(len(list_paper_assets()), 1)
        self.assertEqual(get_paper_asset("2602.12345")["title"], "Updated title")


class ApprovedStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("APPROVED_DB_PATH")
        os.environ["APPROVED_DB_PATH"] = os.path.join(self.tmp.name, "approved.db")

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("APPROVED_DB_PATH", None)
        else:
            os.environ["APPROVED_DB_PATH"] = self.old_db
        self.tmp.cleanup()

    def test_save_get_and_delete_approved_article(self):
        from approved_storage import delete_approved_article, get_approved_articles, init_approved_db, save_approved_article

        init_approved_db()
        article = {
            "id": 7,
            "source": "GitHub",
            "source_type": "github",
            "title": "owner/repo",
            "url": "https://github.com/owner/repo",
            "published_at": "2026-07-02T10:30:00",
            "summary": "repo",
            "structured_summary": {"what_it_is": "A repo"},
            "category": "Tool",
            "score": 10,
            "metrics": {"stars": 100},
        }

        self.assertEqual(save_approved_article(article), 1)
        self.assertEqual(save_approved_article(article), 0)
        rows = get_approved_articles(source_type="github")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["original_article_id"], 7)
        self.assertEqual(rows[0]["structured_summary"]["what_it_is"], "A repo")

        delete_approved_article(rows[0]["id"])
        self.assertEqual(get_approved_articles(), [])


class DateUtilTests(unittest.TestCase):
    def test_parse_range_and_normalize_dates(self):
        from utils import clean_token, humanize_time_ago, is_within_date_range, normalize_date_for_storage, parse_article_date, redact_sensitive_text

        parsed = parse_article_date("Thu, 02 Jul 2026 10:30:00 GMT")
        self.assertEqual(parsed.date(), date(2026, 7, 2))
        self.assertEqual(parse_article_date(1782988200).date(), date(2026, 7, 2))
        self.assertEqual(parse_article_date((2026, 7, 2, 10, 30, 0, 0, 0, 0)).date(), date(2026, 7, 2))
        self.assertIsNone(parse_article_date("not a date"))
        self.assertTrue(is_within_date_range(parsed, date(2026, 7, 2), date(2026, 7, 2)))
        self.assertFalse(is_within_date_range(parsed, date(2026, 7, 3), date(2026, 7, 4)))
        self.assertEqual(normalize_date_for_storage(parsed), "2026-07-02T10:30:00")
        self.assertEqual(clean_token(" token \n"), "token")
        self.assertIsNone(clean_token("   "))
        self.assertNotIn("hf_secret", redact_sensitive_text("Illegal header value b'Bearer hf_secret '"))
        self.assertFalse(is_within_date_range("2026-07-02T09:00:00", datetime(2026, 7, 2, 10), datetime(2026, 7, 2, 12)))
        self.assertEqual(humanize_time_ago("2026-07-02T10:00:00", datetime(2026, 7, 2, 12)), "Published 2 hours ago")
        self.assertEqual(humanize_time_ago(None), "Unknown publish time")


class SummarizerTests(unittest.TestCase):
    def test_filters_noisy_tags_and_builds_concise_huggingface_summary(self):
        from summarizer import build_huggingface_structured_summary, filter_useful_tags

        tags = ["transformers", "safetensors", "text-generation", "license:mit", "arxiv:1234", "conversational", "en"]
        self.assertEqual(filter_useful_tags(tags, "huggingface"), ["text-generation", "conversational"])

        summary = build_huggingface_structured_summary(
            {"pipeline_tag": "text-generation", "tags": tags, "likes": 3194, "downloads": 159967, "last_modified": datetime(2026, 7, 2)}
        )
        self.assertLessEqual(len(summary["what_it_is"]), 180)
        self.assertLessEqual(len(summary["why_it_matters"]), 220)
        self.assertLessEqual(len(summary["best_use_cases"]), 3)
        self.assertLessEqual(len(summary["key_signals"]), 4)
        self.assertNotIn("safetensors", str(summary))

    def test_builds_concise_github_summary_without_readme_dump(self):
        from summarizer import build_github_structured_summary

        summary = build_github_structured_summary(
            {
                "description": "An open-source framework for building LLM agents with tool use and workflow automation. " * 8,
                "topics": ["llm", "agents", "rag", "license:mit"],
                "stars": 4800,
                "forks": 200,
                "language": "Python",
                "published_at": datetime(2026, 7, 2),
            }
        )
        self.assertLessEqual(len(summary["what_it_is"]), 180)
        self.assertIn("4,800 stars", summary["key_signals"])
        self.assertNotIn("license:mit", str(summary))


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

    def test_rss_uses_configured_source_group_and_diagnostics(self):
        from connectors import fetch_rss_articles

        diagnostics = {}
        feed = [{"name": "OpenAI News", "url": "https://example.com/feed", "source_group": "company_news"}]
        entry = {"title": "AI story", "link": "https://example.com/ai", "published": "Thu, 02 Jul 2026 00:00:00 GMT"}
        with patch("connectors.RSS_FEEDS", feed), patch("connectors.feedparser.parse") as parse:
            parse.return_value = Mock(feed=Mock(get=lambda key, default=None: "Ignored"), entries=[entry])
            articles = fetch_rss_articles(diagnostics=diagnostics)

        self.assertEqual(articles[0]["source"], "OpenAI News")
        self.assertEqual(articles[0]["connector"], "rss")
        self.assertEqual(articles[0]["source_group"], "company_news")
        self.assertEqual(diagnostics["feeds"]["OpenAI News"]["raw"], 1)

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
            response.json.return_value = [1, 2] if url.endswith(("topstories.json", "newstories.json", "beststories.json")) else {
                "title": "Developer tool",
                "url": "https://example.com/dev",
                "time": 1782950400,
                "score": 25,
                "descendants": 4,
                "text": "summary",
            }
            return response

        diagnostics = {}
        with patch("connectors.requests.get", side_effect=fake_get):
            articles = fetch_hacker_news(limit=1, diagnostics=diagnostics)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "Hacker News")
        self.assertEqual(articles[0]["url"], "https://example.com/dev")
        self.assertEqual(articles[0]["source_group"], "developer_trends")
        self.assertEqual(diagnostics["raw_ids"], 2)
        self.assertEqual(diagnostics["after_scoring"], 1)

    def test_hacker_news_filters_selected_date_range(self):
        from connectors import fetch_hacker_news

        def fake_get(url, timeout):
            response = Mock()
            response.raise_for_status.return_value = None
            if url.endswith(("topstories.json", "newstories.json", "beststories.json")):
                response.json.return_value = [1, 2]
            elif url.endswith("/1.json"):
                response.json.return_value = {"title": "Fresh AI", "url": "https://example.com/fresh", "time": 1782950400, "score": 21}
            else:
                response.json.return_value = {"title": "Old AI", "url": "https://example.com/old", "time": 1782777600, "score": 21}
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
            <author><name>Ada Lovelace</name></author>
          </entry>
        </feed>"""
        response = Mock(text=xml)
        response.raise_for_status.return_value = None

        with patch("connectors.requests.get", return_value=response):
            articles = fetch_arxiv_ai(limit=1)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "arXiv")
        self.assertEqual(articles[0]["url"], "https://arxiv.org/abs/1234.5678")
        self.assertEqual(articles[0]["category"], "Research")
        self.assertEqual(articles[0]["metrics"]["authors"], ["Ada Lovelace"])

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

    def test_huggingface_models_normalize_and_filter(self):
        from connectors import fetch_huggingface_models

        fresh = Mock(
            modelId="org/fresh-model",
            last_modified=datetime(2026, 7, 2, 10, 30),
            tags=["text-generation", "llm"],
            likes=12,
            downloads=345,
        )
        old = Mock(
            modelId="org/old-model",
            last_modified=datetime(2026, 6, 30, 10, 30),
            tags=["text-generation"],
            likes=1,
            downloads=2,
        )
        api = Mock()
        api.list_models.return_value = [fresh, old]

        with patch("connectors.HfApi", return_value=api) as hf_api:
            articles = fetch_huggingface_models(
                start_date=date(2026, 7, 2),
                end_date=date(2026, 7, 2),
                limit=5,
                huggingface_token=" token ",
            )

        hf_api.assert_called_once_with(token="token")
        self.assertEqual([article["url"] for article in articles], ["https://huggingface.co/org/fresh-model"])
        self.assertEqual(articles[0]["source_type"], "huggingface")
        self.assertEqual(articles[0]["category"], "Model")
        self.assertEqual(articles[0]["metrics"]["likes"], 12)
        self.assertNotIn("safetensors", articles[0]["summary"])

    def test_huggingface_uses_supported_list_models_arguments(self):
        from connectors import fetch_huggingface_models

        api = Mock()
        api.list_models.return_value = [
            Mock(modelId="org/model", last_modified=datetime(2026, 7, 2, 10, 30), tags=["llm"], likes=1, downloads=0)
        ]

        with patch("connectors.HfApi", return_value=api):
            articles = fetch_huggingface_models(limit=1, huggingface_token="token")

        self.assertNotIn("direction", api.list_models.call_args.kwargs)
        self.assertEqual(len(articles), 1)
        self.assertIn("what_it_is", articles[0]["structured_summary"])

    def test_github_repositories_normalize_filter_and_use_token(self):
        from connectors import fetch_github_repositories

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [
                {
                    "full_name": "owner/agent",
                    "html_url": "https://github.com/owner/agent",
                    "created_at": "2026-07-02T10:30:00Z",
                    "pushed_at": "2026-07-02T12:00:00Z",
                    "description": "LLM agent framework",
                    "stargazers_count": 200,
                    "forks_count": 20,
                    "open_issues_count": 3,
                    "topics": ["llm", "agents"],
                },
                {
                    "full_name": "owner/old",
                    "html_url": "https://github.com/owner/old",
                    "created_at": "2026-06-30T10:30:00Z",
                    "pushed_at": "2026-06-30T12:00:00Z",
                    "description": "old ai",
                    "stargazers_count": 1,
                    "forks_count": 0,
                    "open_issues_count": 0,
                    "topics": ["ai"],
                },
            ]
        }

        diagnostics = {}
        with patch("connectors.requests.get", return_value=response) as get:
            articles = fetch_github_repositories(
                start_date=date(2026, 7, 2),
                end_date=date(2026, 7, 2),
                limit=1,
                github_token=" token ",
                diagnostics=diagnostics,
            )

        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer token")
        self.assertEqual([article["url"] for article in articles], ["https://github.com/owner/agent"])
        self.assertEqual(articles[0]["source_type"], "github")
        self.assertEqual(articles[0]["category"], "Tool")
        self.assertEqual(articles[0]["metrics"]["stars"], 200)
        self.assertIn("what_it_is", articles[0]["structured_summary"])
        self.assertEqual(articles[0]["source_group"], "developer_trends")
        self.assertEqual(diagnostics["token_configured"], True)
        self.assertGreaterEqual(diagnostics["raw_items"], 2)

    def test_github_uses_api_version_and_fallback_without_date(self):
        from connectors import fetch_github_repositories

        empty = Mock(status_code=200)
        empty.raise_for_status.return_value = None
        empty.json.return_value = {"items": []}
        hit = Mock(status_code=200)
        hit.raise_for_status.return_value = None
        hit.json.return_value = {
            "items": [
                {
                    "full_name": "owner/repo",
                    "html_url": "https://github.com/owner/repo",
                    "pushed_at": "2026-06-01T00:00:00Z",
                    "updated_at": "2026-06-01T00:00:00Z",
                    "created_at": "2026-01-01T00:00:00Z",
                    "description": None,
                    "stargazers_count": 5,
                    "forks_count": 1,
                    "open_issues_count": 0,
                    "topics": ["llm"],
                }
            ]
        }

        with patch("connectors.GITHUB_QUERIES", ["topic:llm"]), patch(
            "connectors.GITHUB_FALLBACK_QUERIES", ["topic:llm"]
        ), patch("connectors.requests.get", side_effect=[empty, hit]) as get:
            articles = fetch_github_repositories(start_date=date(2026, 7, 2), end_date=date(2026, 7, 2), limit=1, github_token="token")

        search_call = get.call_args_list[-2]
        self.assertEqual(search_call.kwargs["headers"]["X-GitHub-Api-Version"], "2022-11-28")
        self.assertNotIn("pushed:", search_call.kwargs["params"]["q"])
        self.assertEqual([article["url"] for article in articles], ["https://github.com/owner/repo"])

    def test_youtube_videos_normalize_and_filter(self):
        from connectors import fetch_youtube_videos

        entries = [
            {
                "title": "Fresh AI video",
                "link": "https://youtube.com/watch?v=fresh",
                "published": "2026-07-02T10:30:00Z",
                "summary": "LLM tutorial",
            },
            {
                "title": "Old AI video",
                "link": "https://youtube.com/watch?v=old",
                "published": "2026-06-30T10:30:00Z",
                "summary": "old",
            },
        ]
        feeds = [{"name": "AI Channel", "url": "https://youtube.example/feed", "topic": "AI"}]
        with patch("connectors.YOUTUBE_CHANNEL_FEEDS", feeds), patch("connectors.feedparser.parse") as parse:
            parse.return_value = Mock(entries=entries)
            articles = fetch_youtube_videos(start_date=date(2026, 7, 2), end_date=date(2026, 7, 2), limit=5)

        self.assertEqual([article["url"] for article in articles], ["https://youtube.com/watch?v=fresh"])
        self.assertEqual(articles[0]["source"], "YouTube - AI Channel")
        self.assertEqual(articles[0]["source_type"], "youtube")
        self.assertEqual(articles[0]["category"], "Video")

    def test_telegram_parses_channels_and_normalizes_message(self):
        from telegram_connector import _normalize_message, parse_channel_usernames

        message = Mock(
            id=42,
            message="New AI agent framework\nhttps://example.com",
            date=datetime(2026, 7, 2, 10, 30),
            views=123,
            forwards=4,
            replies=Mock(replies=2),
        )

        self.assertEqual(parse_channel_usernames("@OpenAINews\n\n some_ai_channel "), ["OpenAINews", "some_ai_channel"])
        article = _normalize_message(
            message,
            {"name": "OpenAI News", "username": "OpenAINews", "source_group": "social_news", "quality_weight": 1.5},
        )

        self.assertEqual(article["source"], "Telegram - OpenAI News")
        self.assertEqual(article["source_type"], "telegram")
        self.assertEqual(article["connector"], "telegram")
        self.assertEqual(article["source_group"], "social_news")
        self.assertEqual(article["url"], "https://t.me/OpenAINews/42")
        self.assertEqual(article["metrics"]["views"], 123)
        self.assertEqual(article["metrics"]["forwards"], 4)
        self.assertEqual(article["metrics"]["replies"], 2)

    def test_telegram_connector_missing_config_reports_safe_error(self):
        from telegram_connector import fetch_telegram_posts_sync

        diagnostics = {}
        articles = fetch_telegram_posts_sync(
            channels=["OpenAINews"],
            telegram_api_id=None,
            telegram_api_hash=" secret ",
            telegram_session_name="missing-session",
            diagnostics=diagnostics,
        )

        self.assertEqual(articles, [])
        self.assertFalse(diagnostics["api_id_configured"])
        self.assertTrue(diagnostics["api_hash_configured"])
        self.assertIn("Telegram API ID/API Hash are required.", diagnostics["errors"])


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

    def test_scores_source_specific_metrics(self):
        from ranker import classify_and_score

        github = classify_and_score(
            {
                "source_type": "github",
                "title": "LLM agent framework",
                "summary": "RAG generative ai",
                "metrics": {"stars": 100, "forks": 10},
            }
        )
        huggingface = classify_and_score(
            {
                "source_type": "huggingface",
                "title": "org/model",
                "summary": "text-generation multimodal",
                "metrics": {"likes": 20, "downloads": 500},
            }
        )

        self.assertEqual(github["category"], "Tool")
        self.assertGreater(github["score"], 100)
        self.assertEqual(huggingface["category"], "Model")
        self.assertGreater(huggingface["score"], 20)

        arxiv = classify_and_score({"source_type": "arxiv", "title": "A theorem", "summary": ""})
        hn = classify_and_score({"source_type": "hacker_news", "title": "Developer startup", "summary": "", "metrics": {"hn_score": 25}})
        self.assertEqual(arxiv["category"], "Research")
        self.assertGreater(arxiv["score"], 0)
        self.assertGreater(hn["score"], 0)

    def test_scores_telegram_posts(self):
        from ranker import classify_and_score

        telegram = classify_and_score(
            {
                "source_type": "telegram",
                "title": "New LLM agent startup launches",
                "summary": "AI developer tool with https://example.com",
                "metrics": {"views": 1200, "forwards": 30, "quality_weight": 1.2},
            }
        )

        self.assertEqual(telegram["category"], "AI")
        self.assertGreater(telegram["score"], 0)


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

        with patch("agent.init_db") as init_db, patch("agent.create_search_session", return_value="session-1"), patch(
            "agent.update_search_session_count"
        ), patch("agent.save_articles", return_value=1) as save_articles, patch(
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

        with patch("agent.init_db"), patch("agent.create_search_session", return_value="session-1"), patch(
            "agent.update_search_session_count"
        ), patch("agent.save_articles", return_value=1) as save_articles, patch(
            "agent.fetch_rss_articles", return_value=[fresh, old, undated]
        ) as rss, patch("agent.fetch_hacker_news", return_value=[]) as hn, patch("agent.fetch_arxiv_ai", return_value=[]) as arxiv:
            articles = run_news_agent(start_date=date(2026, 7, 2), end_date=date(2026, 7, 2))

        self.assertEqual(rss.call_args.kwargs["start_date"], date(2026, 7, 2))
        self.assertEqual(hn.call_args.kwargs["start_date"], date(2026, 7, 2))
        self.assertEqual(arxiv.call_args.kwargs["start_date"], date(2026, 7, 2))
        save_articles.assert_called_once()
        self.assertEqual([article["url"] for article in articles], ["https://example.com/fresh"])
        self.assertEqual(articles[0]["published_at"], "2026-07-02T10:30:00")

    def test_run_news_agent_only_runs_selected_sources(self):
        from agent import run_news_agent

        item = {
            "source": "Hacker News",
            "source_type": "hacker_news",
            "title": "LLM developer tool",
            "url": "https://example.com/hn",
            "published_at": "2026-07-02T10:30:00",
            "summary": "AI API",
        }

        with patch("agent.init_db"), patch("agent.create_search_session", return_value="session-1"), patch(
            "agent.update_search_session_count"
        ), patch("agent.save_articles", return_value=1), patch("agent.fetch_rss_articles") as rss, patch(
            "agent.fetch_hacker_news", return_value=[item]
        ) as hn, patch("agent.fetch_arxiv_ai") as arxiv:
            articles = run_news_agent(selected_sources=["hacker_news"])

        rss.assert_not_called()
        hn.assert_called_once()
        arxiv.assert_not_called()
        self.assertEqual([article["source_type"] for article in articles], ["hacker_news"])

    def test_run_news_agent_report_and_selected_github_huggingface(self):
        from agent import run_news_agent

        github = {
            "source": "GitHub",
            "source_type": "github",
            "title": "owner/repo",
            "url": "https://github.com/owner/repo",
            "published_at": "2026-07-02T10:30:00",
            "summary": "",
            "metrics": {"stars": 1},
        }
        hf = {
            "source": "Hugging Face",
            "source_type": "huggingface",
            "title": "org/model",
            "url": "https://huggingface.co/org/model",
            "published_at": "2026-07-02T10:30:00",
            "summary": "",
            "metrics": {},
        }

        with patch("agent.init_db"), patch("agent.create_search_session", return_value="session-1"), patch(
            "agent.update_search_session_count"
        ), patch("agent.save_articles", side_effect=[1, 1]), patch("agent.fetch_github_repositories", return_value=[github]), patch(
            "agent.fetch_huggingface_models", return_value=[hf]
        ):
            articles = run_news_agent(selected_sources=["github", "huggingface"])

        self.assertEqual([article["source_type"] for article in articles], ["huggingface", "github"])
        self.assertEqual(articles.search_session_id, "session-1")
        self.assertEqual(articles.report["sources"]["GitHub"], 1)
        self.assertEqual(articles.report["sources"]["Hugging Face"], 1)
        self.assertEqual(articles.report["saved"], 2)
        self.assertEqual(articles.report["source_details"]["GitHub"]["saved"], 1)
        self.assertIn("github", articles.report["diagnostics"])

    def test_run_news_agent_passes_telegram_config(self):
        from agent import run_news_agent

        telegram = {
            "source": "Telegram - AI Channel",
            "source_type": "telegram",
            "title": "OpenAI agent update",
            "url": "https://t.me/ai/1",
            "published_at": "2026-07-02T10:30:00",
            "summary": "LLM developer startup",
            "metrics": {"views": 100},
        }

        with patch("agent.init_db"), patch("agent.create_search_session", return_value="session-1"), patch(
            "agent.update_search_session_count"
        ), patch("agent.save_articles", return_value=1) as save_articles, patch(
            "agent.fetch_telegram_posts_sync", return_value=[telegram]
        ) as telegram_fetch:
            articles = run_news_agent(
                selected_sources=["telegram"],
                telegram_api_id=" 12345 ",
                telegram_api_hash=" hash ",
                telegram_session_name=" news_session ",
                telegram_channels=["@ai"],
            )

        telegram_fetch.assert_called_once()
        self.assertEqual(telegram_fetch.call_args.kwargs["telegram_api_id"], "12345")
        self.assertEqual(telegram_fetch.call_args.kwargs["telegram_api_hash"], "hash")
        self.assertEqual(telegram_fetch.call_args.kwargs["telegram_session_name"], "news_session")
        self.assertEqual(telegram_fetch.call_args.kwargs["channels"], ["@ai"])
        save_articles.assert_called_once()
        self.assertEqual(articles[0]["source_type"], "telegram")
        self.assertEqual(articles.report["sources"]["Telegram - AI Channel"], 1)
        self.assertIn("telegram", articles.report["diagnostics"])


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

    def test_resolve_tokens_prefers_session_over_environment(self):
        from app import resolve_tokens

        env = {
            "GITHUB_TOKEN": " env-gh ",
            "HUGGINGFACE_TOKEN": " env-hf ",
            "YOUTUBE_API_KEY": " env-yt ",
            "TELEGRAM_API_ID": " 123 ",
            "TELEGRAM_API_HASH": " env-hash ",
            "TELEGRAM_SESSION_NAME": " env-session ",
        }
        tokens = resolve_tokens({"github_token": " session-gh ", "telegram_api_hash": " session-hash "}, env)

        self.assertEqual(tokens["github_token"], "session-gh")
        self.assertEqual(tokens["huggingface_token"], "env-hf")
        self.assertEqual(tokens["youtube_api_key"], "env-yt")
        self.assertEqual(tokens["telegram_api_id"], "123")
        self.assertEqual(tokens["telegram_api_hash"], "session-hash")
        self.assertEqual(tokens["telegram_session_name"], "env-session")

    def test_resolve_time_range_last_24_hours(self):
        from app import resolve_time_range

        start, end, custom = resolve_time_range("Last 24 hours")
        self.assertFalse(custom)
        self.assertLessEqual(end - start, timedelta(hours=24, seconds=1))

    def test_article_cards_only_expose_approve_action(self):
        with open("app.py", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn('st.button("Approve"', source)
        self.assertNotIn('st.button("Reject"', source)
        self.assertNotIn('st.button("Reset to New"', source)


class DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_do_not_expose_tokens(self):
        from diagnostics import test_arxiv_connector, test_github_connector, test_hacker_news_connector, test_huggingface_connection

        with patch("diagnostics.fetch_github_repositories", return_value=[{"title": "repo"}]) as github:
            result = test_github_connector(github_token=" secret ")

        self.assertTrue(result["ok"])
        self.assertEqual(result["items_found"], 1)
        self.assertIn("diagnostics", result)
        self.assertIn("diagnostics", github.call_args.kwargs)
        self.assertNotIn("secret", str(result))

        with patch("diagnostics.HfApi", side_effect=ValueError("Illegal header value b'Bearer hf_secret '")):
            result = test_huggingface_connection(huggingface_token=" hf_secret ")

        self.assertFalse(result["ok"])
        self.assertNotIn("hf_secret", str(result))

        with patch("diagnostics.fetch_hacker_news", return_value=[]):
            self.assertTrue(test_hacker_news_connector()["ok"])
        with patch("diagnostics.fetch_arxiv_ai", return_value=[]):
            self.assertTrue(test_arxiv_connector()["ok"])


if __name__ == "__main__":
    unittest.main()
