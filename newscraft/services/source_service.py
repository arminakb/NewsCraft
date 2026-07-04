from newscraft.repositories.source_repository import SourceRepository


class SourceService:
    def __init__(self, db, repo=None):
        self.repo = repo or SourceRepository(db)

    def list(self):
        return self.repo.list()

    def create(self, data):
        return self.repo.create(data)

    def update(self, source_id, data):
        return self.repo.update(source_id, data)

    def health(self):
        return {"status": "ok", "message": "source configuration API is available"}
