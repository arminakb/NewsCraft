import asyncio
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ingestion.workflow import (
    FetchedSourceBatch,
    IngestionWorkflow,
    PreparedIngestionRun,
    PreparedSource,
    SourcePersistResult,
)
from app.source_collections.repository import (
    SourceCollectionLimitExceeded,
    normalize_description,
    normalize_source_collection_name,
)
from app.source_collections.schemas import (
    SourceCollectionCreateIn,
    SourceCollectionIngestIn,
    SourceCollectionUpdateIn,
)


class _Transaction(AbstractAsyncContextManager):
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        assert not self.session.active
        self.session.active = True

    async def __aexit__(self, exc_type, exc, traceback):
        self.session.active = False


class _Session:
    def __init__(self):
        self.active = False

    def begin(self, _label=None):
        return _Transaction(self)

    def in_transaction(self):
        return self.active


def _source(index: int) -> PreparedSource:
    return PreparedSource(
        id=uuid4(),
        name=f"source-{index}",
        platform="rss",
        feed_url=f"https://example.com/{index}.xml",
        telegram_username=None,
        default_timezone="UTC",
        etag=None,
        last_modified=None,
    )


def test_source_collection_names_are_trimmed_and_casefolded():
    assert normalize_source_collection_name("  Morning News  ") == ("Morning News", "morning news")
    assert normalize_description("  Operations  ") == "Operations"
    assert normalize_description("  ") is None


def test_source_collection_create_accepts_empty_membership_and_forbids_ui_fields():
    payload = SourceCollectionCreateIn.model_validate({"name": "  AI Sources  "})

    assert payload.model_dump(exclude_none=True) == {"name": "AI Sources"}
    with pytest.raises(ValidationError):
        SourceCollectionCreateIn.model_validate({"name": "AI Sources", "source_ids": []})
    with pytest.raises(ValidationError):
        SourceCollectionCreateIn.model_validate({"name": "AI Sources", "description": 42})


def test_source_collection_update_requires_a_real_field():
    with pytest.raises(ValueError):
        SourceCollectionUpdateIn()
    assert SourceCollectionUpdateIn(description=None).model_fields_set == {"description"}


def test_collection_ingest_mode_is_explicit_and_strict():
    assert SourceCollectionIngestIn.model_validate({}).mode == "once"
    assert SourceCollectionIngestIn.model_validate({"mode": "continuous"}).mode == "continuous"
    with pytest.raises(ValidationError):
        SourceCollectionIngestIn.model_validate({"mode": "feed"})
    with pytest.raises(ValidationError):
        SourceCollectionIngestIn.model_validate({"mode": "once", "source_ids": []})


def test_source_collection_limit_error_is_structured():
    collection_id = uuid4()
    error = SourceCollectionLimitExceeded(
        collection_id=collection_id,
        current_count=99,
        requested_additions=2,
    )
    assert error.collection_id == collection_id
    assert error.current_count == 99
    assert error.requested_additions == 2
    assert "100" in str(error)


@pytest.mark.asyncio
async def test_ingestion_fetch_window_is_bounded_by_source_concurrency(monkeypatch):
    class WindowWorkflow(IngestionWorkflow):
        def __init__(self):
            super().__init__()
            self.sources = tuple(_source(index) for index in range(7))
            self.active_fetches = 0
            self.maximum_active_fetches = 0

        async def prepare_run(self, session, *, platforms, source_ids, trigger):
            return PreparedIngestionRun(run_id=uuid4(), sources=self.sources)

        async def fetch_source(self, source):
            self.active_fetches += 1
            self.maximum_active_fetches = max(self.maximum_active_fetches, self.active_fetches)
            await asyncio.sleep(0.001)
            self.active_fetches -= 1
            return FetchedSourceBatch(
                source=source,
                request_url=source.feed_url or "",
                final_url=source.feed_url or "",
                http_status=200,
                headers={},
                content_type="application/rss+xml",
                raw_text="<rss />",
                parser_warnings=(),
                parsed_items=(),
            )

        async def persist_source(self, session, *, run_id, batch):
            return SourcePersistResult(fetched=1)

        async def finish_run(self, session, *, run_id, stats):
            return None

    monkeypatch.setattr("app.ingestion.workflow.settings.ingestion_source_concurrency", 2)
    workflow = WindowWorkflow()
    result = await workflow.run(
        session=_Session(),
        platforms=None,
        source_ids=None,
        trigger="test",
    )

    assert result["checked"] == 7
    assert result["failed"] == 0
    assert workflow.maximum_active_fetches <= 2
