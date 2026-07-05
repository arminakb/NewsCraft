from uuid import uuid4

from app.workflows.drafts import DraftService


class FakeSession:
    def __init__(self):
        self.added = None
        self.flushed = False

    def add(self, obj):
        self.added = obj

    async def flush(self):
        self.flushed = True


async def test_draft_service_creates_draft_for_content_item():
    session = FakeSession()
    content_item_id = uuid4()

    draft = await DraftService(session).create(
        content_item_id=content_item_id,
        platform="telegram",
        draft_text="Draft text",
        human_notes="tighten intro",
    )

    assert draft.content_item_id == content_item_id
    assert draft.platform == "telegram"
    assert draft.draft_text == "Draft text"
    assert draft.status == "draft"
    assert session.added is draft
    assert session.flushed is True
