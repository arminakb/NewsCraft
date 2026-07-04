from newscraft.repositories.content_draft_repository import ContentDraftRepository


class ContentPipelineService:
    def __init__(self, db, repo=None):
        self.repo = repo or ContentDraftRepository(db)

    def list(self, **filters):
        return self.repo.list(**filters)

    def create(self, payload):
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload
        return self.repo.create(data)

    def update(self, draft_id, payload):
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload
        return self.repo.update(draft_id, data)
