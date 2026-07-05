from types import SimpleNamespace
from uuid import uuid4

from app.workflows.approval import ApprovalService


class FakeSession:
    def __init__(self, item):
        self.item = item
        self.flushed = False

    async def get(self, model, item_id):
        return self.item if self.item.id == item_id else None

    async def flush(self):
        self.flushed = True


async def test_approval_marks_content_item_approved():
    item = SimpleNamespace(id=uuid4(), status="new", metrics={})
    session = FakeSession(item)

    result = await ApprovalService(session).approve(item.id, notes="ready")

    assert result.status == "approved"
    assert result.metrics["approval"]["notes"] == "ready"
    assert session.flushed is True
