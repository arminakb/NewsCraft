import os
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
