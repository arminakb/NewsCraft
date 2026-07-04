from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from newscraft.db.models import IngestionRun, SourceRunLog


class IngestionRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, selected_sources):
        run = IngestionRun(selected_sources=selected_sources)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def finish(self, run, status="succeeded", **values):
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        for key, value in values.items():
            setattr(run, key, value)
        self.db.commit()
        self.db.refresh(run)
        return run

    def list(self, limit=50):
        return list(self.db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)))

    def get(self, run_id: int):
        return self.db.get(IngestionRun, run_id)

    def log_source(self, run_id: int, **values):
        log = SourceRunLog(ingestion_run_id=run_id, **values)
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log
