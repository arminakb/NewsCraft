from newscraft.db.session import SessionLocal
from newscraft.repositories.source_repository import SourceRepository


DEFAULT_SOURCES = [
    {"name": "RSS feeds", "source_type": "rss", "connector": "rss", "category": "General"},
    {"name": "Hacker News", "source_type": "hacker_news", "connector": "hacker_news", "category": "Tech"},
    {"name": "arXiv", "source_type": "arxiv", "connector": "arxiv", "category": "Research"},
    {"name": "GitHub", "source_type": "github", "connector": "github", "category": "Tool"},
    {"name": "Hugging Face", "source_type": "huggingface", "connector": "huggingface", "category": "Model"},
    {"name": "YouTube RSS", "source_type": "youtube", "connector": "youtube", "category": "Video"},
    {"name": "Telegram", "source_type": "telegram", "connector": "telegram", "category": "Social"},
]


def main():
    with SessionLocal() as db:
        repo = SourceRepository(db)
        existing = {source.connector for source in repo.list()}
        for source in DEFAULT_SOURCES:
            if source["connector"] not in existing:
                repo.create(source)


if __name__ == "__main__":
    main()
