from newscraft.db.session import SessionLocal
from newscraft.ingestion.seed_sources import SEED_SOURCES
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
        existing_keys = {(source.connector, source.url or source.name) for source in repo.list()}
        for source in [*DEFAULT_SOURCES, *SEED_SOURCES]:
            key = (source["connector"], source.get("url") or source["name"])
            if key not in existing_keys:
                repo.create(source)
                existing_keys.add(key)


if __name__ == "__main__":
    main()
