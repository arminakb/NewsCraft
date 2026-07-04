from sqlalchemy import select
from sqlalchemy.orm import Session

from newscraft.db.models import Source


class SourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(self, enabled: bool | None = None):
        stmt = select(Source)
        if enabled is not None:
            stmt = stmt.where(Source.enabled == enabled)
        return list(self.db.scalars(stmt.order_by(Source.name)))

    def create(self, data: dict):
        source = Source(**data)
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def get(self, source_id: int):
        return self.db.get(Source, source_id)

    def update(self, source_id: int, data: dict):
        source = self.get(source_id)
        if not source:
            return None
        for key, value in data.items():
            if value is not None:
                setattr(source, key, value)
        self.db.commit()
        self.db.refresh(source)
        return source
