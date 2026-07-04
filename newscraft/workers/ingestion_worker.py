from newscraft.db.session import SessionLocal
from newscraft.services.ingestion_service import IngestionService


def run_once(selected_sources=None):
    with SessionLocal() as db:
        return IngestionService(db).run(selected_sources=selected_sources)


if __name__ == "__main__":
    run_once()
