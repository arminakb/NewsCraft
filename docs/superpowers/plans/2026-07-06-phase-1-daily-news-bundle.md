# Phase 1 Daily News Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one command that collects a desired date range from GDELT, Google News RSS, curated RSS feeds, public Telegram channels, and Hacker News, extracts full article text and images where available, and exports an agent-readable folder.

**Architecture:** Keep the existing NewsCraft ingestion backend as the storage core. Existing RSS and public Telegram ingestion continue through `IngestionService`; new no-signup discovery connectors produce normalized URL candidates that are enriched by a shared article extractor and persisted through the existing `content_items`, `source_items`, `media_assets`, and `item_media` tables. A daily bundle exporter writes `today-news/YYYY-MM-DD/` with markdown, JSON, and image references for the writing agent.

**Tech Stack:** FastAPI backend package, SQLAlchemy async ORM, `httpx`, `feedparser`, BeautifulSoup/lxml, new `trafilatura` dependency, PostgreSQL, pytest, Docker Compose.

---

## Scope

Phase 1 includes only sources that directly help the agent write from yesterday or a selected date range:

- GDELT for broad no-signup global news discovery.
- Google News RSS for no-signup topic discovery.
- Existing curated RSS feed ingestion.
- Existing public Telegram channel ingestion.
- Hacker News for AI/tech/startup trend signal.
- Full webpage extraction for article URLs.
- Main image extraction and download.
- Date-range folder export.

Phase 1 excludes YouTube, Reddit, X, TikTok, Instagram, Threads, economic statistics APIs, disaster/weather APIs, and posting to social channels.

## Target Command

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.daily_bundle \
  --start 2026-07-05 \
  --end 2026-07-06 \
  --topic "AI" \
  --topic "economy" \
  --topic "politics" \
  --output ../today-news/2026-07-05 \
  --download-media
```

Expected output:

```text
today-news/2026-07-05/
├── index.md
├── items.json
├── sources.json
├── articles/
│   ├── 001-openai-example.md
│   └── 002-market-example.md
└── images/
    ├── 001.jpg
    └── 002.webp
```

## File Structure

- Create: `backend/app/discovery/__init__.py`
- Create: `backend/app/discovery/models.py`
- Create: `backend/app/discovery/gdelt.py`
- Create: `backend/app/discovery/google_news.py`
- Create: `backend/app/discovery/hackernews.py`
- Create: `backend/app/discovery/article_extractor.py`
- Create: `backend/app/discovery/service.py`
- Create: `backend/app/daily_bundle/__init__.py`
- Create: `backend/app/daily_bundle/date_range.py`
- Create: `backend/app/daily_bundle/exporter.py`
- Create: `backend/app/daily_bundle/__main__.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/worker.py`
- Modify: `backend/pyproject.toml`
- Modify: `README.md`
- Modify: `docs/ingestion-backend.md`
- Test: `backend/tests/test_daily_bundle_date_range.py`
- Test: `backend/tests/test_discovery_gdelt.py`
- Test: `backend/tests/test_discovery_google_news.py`
- Test: `backend/tests/test_discovery_hackernews.py`
- Test: `backend/tests/test_article_extractor.py`
- Test: `backend/tests/test_daily_bundle_exporter.py`
- Test: `backend/tests/test_daily_bundle_service.py`

## Data Contract

Every discovery connector returns:

```python
@dataclass(slots=True)
class DiscoveryItem:
    source_platform: str
    source_name: str
    external_id: str
    title: str
    url: str | None
    summary: str
    published_at: datetime | None
    image_url: str | None
    author: str | None
    categories: list[str]
    metadata: dict[str, Any]
```

Every extracted article returns:

```python
@dataclass(slots=True)
class ExtractedArticle:
    url: str
    final_url: str
    title: str
    summary: str
    content_text: str
    content_html: str | None
    author: str | None
    published_at: datetime | None
    image_url: str | None
    extraction_status: str
    extraction_warnings: list[str]
```

## Task 1: Add Shared Discovery Models

**Files:**
- Create: `backend/app/discovery/__init__.py`
- Create: `backend/app/discovery/models.py`
- Test: `backend/tests/test_discovery_models.py`

- [ ] **Step 1: Write model tests**

Create `backend/tests/test_discovery_models.py`:

```python
from datetime import UTC, datetime

from app.discovery.models import DiscoveryItem, ExtractedArticle


def test_discovery_item_stores_source_metadata():
    item = DiscoveryItem(
        source_platform="gdelt",
        source_name="GDELT",
        external_id="https://example.com/a",
        title="Example",
        url="https://example.com/a",
        summary="Summary",
        published_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
        image_url="https://example.com/i.jpg",
        author=None,
        categories=["AI"],
        metadata={"domain": "example.com"},
    )

    assert item.source_platform == "gdelt"
    assert item.url == "https://example.com/a"
    assert item.metadata["domain"] == "example.com"


def test_extracted_article_records_status_and_warnings():
    article = ExtractedArticle(
        url="https://example.com/a",
        final_url="https://example.com/a",
        title="Example",
        summary="Summary",
        content_text="Full article text",
        content_html=None,
        author="Reporter",
        published_at=None,
        image_url=None,
        extraction_status="ok",
        extraction_warnings=[],
    )

    assert article.extraction_status == "ok"
    assert article.content_text == "Full article text"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_models.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'app.discovery'`.

- [ ] **Step 3: Implement models**

Create `backend/app/discovery/__init__.py`:

```python
"""Discovery connectors for URL-first news collection."""
```

Create `backend/app/discovery/models.py` with the two dataclasses from the Data Contract section.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_models.py -q
```

Expected: `2 passed`.

## Task 2: Add Date-Range Handling

**Files:**
- Create: `backend/app/daily_bundle/__init__.py`
- Create: `backend/app/daily_bundle/date_range.py`
- Test: `backend/tests/test_daily_bundle_date_range.py`

- [ ] **Step 1: Write date-range tests**

Create tests for:

- `parse_date_range("2026-07-05", "2026-07-06", "Asia/Tehran")` returns timezone-aware start/end.
- `default_yesterday("Asia/Tehran", now=datetime(2026, 7, 6, 10, tzinfo=ZoneInfo("Asia/Tehran")))` returns July 5 start to July 6 start.
- invalid range where start is after end raises `ValueError`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_date_range.py -q
```

Expected: fail because `app.daily_bundle.date_range` does not exist.

- [ ] **Step 3: Implement date-range module**

Create `backend/app/daily_bundle/__init__.py`:

```python
"""Daily bundle orchestration and export."""
```

Create `backend/app/daily_bundle/date_range.py` with:

- `parse_date_range(start: str, end: str, timezone_name: str) -> tuple[datetime, datetime]`
- `default_yesterday(timezone_name: str, now: datetime | None = None) -> tuple[datetime, datetime]`

Use `zoneinfo.ZoneInfo`; treat `end` as exclusive midnight.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_date_range.py -q
```

Expected: all date-range tests pass.

## Task 3: Add GDELT Discovery Connector

**Files:**
- Create: `backend/app/discovery/gdelt.py`
- Test: `backend/tests/test_discovery_gdelt.py`

- [ ] **Step 1: Write connector tests with mocked HTTP**

Test that `discover_gdelt(client, start, end, topics, max_records=50)`:

- Calls `https://api.gdeltproject.org/api/v2/doc/doc`.
- Sends `mode=ArtList`, `format=json`, `startdatetime`, `enddatetime`, `maxrecords`, and a topic query.
- Maps articles into `DiscoveryItem`.
- Drops rows without URL.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_gdelt.py -q
```

Expected: fail because connector does not exist.

- [ ] **Step 3: Implement connector**

Create `backend/app/discovery/gdelt.py`:

- Function: `async def discover_gdelt(client: httpx.AsyncClient, start: datetime, end: datetime, topics: list[str], max_records: int = 100) -> list[DiscoveryItem]`
- Build GDELT query from topics with `OR`.
- Convert datetimes to `YYYYMMDDHHMMSS`.
- Use response field `articles`.
- Use `url` as `external_id`.
- Use `seendate` or `socialimage` when available.

- [ ] **Step 4: Run test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_gdelt.py -q
```

Expected: GDELT connector tests pass.

## Task 4: Add Google News RSS Discovery Connector

**Files:**
- Create: `backend/app/discovery/google_news.py`
- Test: `backend/tests/test_discovery_google_news.py`

- [ ] **Step 1: Write connector tests**

Test that `discover_google_news_rss(client, start, end, topics, language="en", region="US")`:

- Builds one RSS search URL per topic.
- Parses feed XML with `feedparser`.
- Maps entries to `DiscoveryItem`.
- Filters by published date between start inclusive and end exclusive.
- Uses Google News entry link as URL for Phase 1.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_google_news.py -q
```

Expected: fail because connector does not exist.

- [ ] **Step 3: Implement connector**

Create `backend/app/discovery/google_news.py`:

- Function: `async def discover_google_news_rss(...) -> list[DiscoveryItem]`
- URL format: `https://news.google.com/rss/search?q=<query>&hl=en-US&gl=US&ceid=US:en`
- Query format should include topic and date range terms: `topic after:YYYY-MM-DD before:YYYY-MM-DD`.
- Parse dates using existing `parse_source_datetime` when possible.

- [ ] **Step 4: Run test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_google_news.py -q
```

Expected: Google News connector tests pass.

## Task 5: Add Hacker News Discovery Connector

**Files:**
- Create: `backend/app/discovery/hackernews.py`
- Test: `backend/tests/test_discovery_hackernews.py`

- [ ] **Step 1: Write connector tests**

Test that `discover_hackernews(client, start, end, lists=("topstories", "newstories", "beststories"), limit=100)`:

- Fetches story ID lists from `https://hacker-news.firebaseio.com/v0/<list>.json`.
- Fetches item details from `https://hacker-news.firebaseio.com/v0/item/<id>.json`.
- Keeps only `type == "story"`.
- Keeps only stories in the date range.
- Emits `DiscoveryItem` with score/comment count in metadata.
- Drops stories with neither `url` nor text.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_hackernews.py -q
```

Expected: fail because connector does not exist.

- [ ] **Step 3: Implement connector**

Create `backend/app/discovery/hackernews.py`:

- Function: `async def discover_hackernews(...) -> list[DiscoveryItem]`
- Convert HN Unix `time` to UTC datetime.
- Use `url` for external articles.
- For Ask HN/text-only stories, use `https://news.ycombinator.com/item?id=<id>` as the URL and include text in summary.

- [ ] **Step 4: Run test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_discovery_hackernews.py -q
```

Expected: Hacker News connector tests pass.

## Task 6: Add Full Article Extractor

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/discovery/article_extractor.py`
- Test: `backend/tests/test_article_extractor.py`

- [ ] **Step 1: Add failing extractor tests**

Test that `extract_article(client, item)`:

- Fetches the article URL.
- Extracts main text from HTML.
- Uses Open Graph title/image when available.
- Falls back to discovery title/summary/image if extraction is weak.
- Emits warning `short_extraction` when extracted text is shorter than discovery summary.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_article_extractor.py -q
```

Expected: fail because extractor does not exist.

- [ ] **Step 3: Add dependency**

Modify `backend/pyproject.toml` dependencies:

```toml
"trafilatura>=2.0",
```

- [ ] **Step 4: Implement extractor**

Create `backend/app/discovery/article_extractor.py`:

- Function: `async def extract_article(client: httpx.AsyncClient, item: DiscoveryItem) -> ExtractedArticle`
- Fetch with `follow_redirects=True`.
- Extract with `trafilatura.extract(..., output_format="json", with_metadata=True)`.
- Parse Open Graph image/title/date with BeautifulSoup.
- Choose image priority: extracted image, `og:image`, `twitter:image`, discovery `image_url`.
- Never fail the whole bundle on one bad URL; return `extraction_status="failed"` with discovery fields when HTTP/extraction fails.

- [ ] **Step 5: Install dependencies and run test**

Run:

```bash
cd backend
.venv/bin/python -m pip install -e ".[dev]"
PYTHONPATH=. .venv/bin/python -m pytest tests/test_article_extractor.py -q
```

Expected: article extractor tests pass.

## Task 7: Persist Discovery Items Through Existing Repository

**Files:**
- Create: `backend/app/discovery/service.py`
- Test: `backend/tests/test_daily_bundle_service.py`

- [ ] **Step 1: Write service tests with fake repository**

Test that `DiscoveryIngestionService.ingest_discovery_items(...)`:

- Ensures a `Source` row exists for `gdelt`, `google_news`, or `hackernews`.
- Converts each `DiscoveryItem` and `ExtractedArticle` to `ParsedSourceItem`.
- Calls existing repository methods: `upsert_source_item`, `upsert_content_item`, `attach_identities`, `upsert_media_assets`, `attach_item_media`.
- Does not duplicate the same canonical URL twice in one run.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_service.py -q
```

Expected: fail because service does not exist.

- [ ] **Step 3: Implement service**

Create `backend/app/discovery/service.py`:

- Class: `DiscoveryIngestionService`
- Method: `async def ingest_discovery_items(self, run_id, platform: str, items: list[DiscoveryItem], extracted: dict[str, ExtractedArticle]) -> dict[str, int]`
- Build media candidates from article image URLs with `kind="image"`, `source_field="article_primary_image"`, `confidence=1.0`.
- Use existing `title_date_fingerprint`, URL normalization, and `IngestionRepository`.

- [ ] **Step 4: Run test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_service.py -q
```

Expected: discovery ingestion service tests pass.

## Task 8: Add Daily Bundle Exporter

**Files:**
- Create: `backend/app/daily_bundle/exporter.py`
- Test: `backend/tests/test_daily_bundle_exporter.py`

- [ ] **Step 1: Write exporter tests**

Test that `export_daily_bundle(session, start, end, output_path)`:

- Selects `ContentItem.sort_at >= start` and `< end`.
- Orders by score descending then `sort_at` descending.
- Writes `index.md`.
- Writes `items.json`.
- Writes one markdown file per item under `articles/`.
- Includes title, URL, source platform, published date, score, summary, content text, image path/url, and provenance metadata.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_exporter.py -q
```

Expected: fail because exporter does not exist.

- [ ] **Step 3: Implement exporter**

Create `backend/app/daily_bundle/exporter.py`:

- Function: `async def export_daily_bundle(session, start: datetime, end: datetime, output_path: Path, limit: int = 250) -> dict[str, Any]`
- Use `selectinload(ContentItem.primary_media)`.
- Generate safe filenames with item rank and title slug.
- Write UTF-8 markdown and JSON.
- If `primary_media.storage_path` exists, copy image into `images/`; otherwise include external image URL.

- [ ] **Step 4: Run test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_exporter.py -q
```

Expected: exporter tests pass.

## Task 9: Add Daily Bundle CLI

**Files:**
- Create: `backend/app/daily_bundle/__main__.py`
- Modify: `backend/app/worker.py`
- Test: `backend/tests/test_daily_bundle_cli.py`

- [ ] **Step 1: Write CLI tests**

Test that the CLI:

- Accepts `--start`, `--end`, `--topic`, `--output`, `--timezone`, `--download-media`.
- Defaults to yesterday when no start/end is provided.
- Runs existing RSS/Telegram ingestion first.
- Runs GDELT, Google News RSS, and Hacker News discovery.
- Runs extraction.
- Downloads media when requested.
- Exports the folder.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_cli.py -q
```

Expected: fail because CLI does not exist.

- [ ] **Step 3: Implement CLI**

Create `backend/app/daily_bundle/__main__.py`:

- Parse args with `argparse`.
- Build one `httpx.AsyncClient` with proxy settings from `settings`.
- Create one ingest run with trigger `daily_bundle`.
- Run `IngestionService.run_once(platforms=["rss", "atom", "telegram_public"], trigger="daily_bundle")`.
- Run `discover_gdelt`, `discover_google_news_rss`, and `discover_hackernews`.
- Extract URLs concurrently with a small semaphore, default concurrency `8`.
- Persist discovery items.
- Run `MediaDownloader.download_missing()` when `--download-media` is set.
- Export bundle.
- Print final counts.

Modify `backend/app/worker.py` only if needed to share HTTP client construction; do not change existing worker behavior.

- [ ] **Step 4: Run CLI test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_daily_bundle_cli.py -q
```

Expected: CLI tests pass.

## Task 10: Add Docker And Documentation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `docs/ingestion-backend.md`
- Test: `backend/tests/test_docker_config.py`

- [ ] **Step 1: Update Docker config test**

Extend `backend/tests/test_docker_config.py` to assert a documented daily bundle command exists in Compose or README:

```text
python -m app.daily_bundle
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_docker_config.py -q
```

Expected: fail until docs/config mention the command.

- [ ] **Step 3: Document usage**

Add to `README.md`:

```bash
docker compose run --rm api python -m app.daily_bundle \
  --start 2026-07-05 \
  --end 2026-07-06 \
  --topic "AI" \
  --topic "economy" \
  --output /workspace/today-news/2026-07-05 \
  --download-media
```

Add to `docs/ingestion-backend.md`:

- Phase 1 source list.
- Date range behavior.
- Output folder structure.
- Statement that YouTube/Reddit are deferred to Phase 2.

- [ ] **Step 4: Run config/docs test**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_docker_config.py -q
```

Expected: Docker/docs test passes.

## Final Verification

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
git diff --check
```

Expected:

```text
all tests pass
All checks passed!
git diff --check exits 0
```

## Manual Smoke Test

Run with Docker:

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.daily_bundle \
  --start 2026-07-05 \
  --end 2026-07-06 \
  --topic "AI" \
  --topic "economy" \
  --topic "politics" \
  --output /workspace/today-news/2026-07-05 \
  --download-media
```

Expected:

- Command exits 0.
- Output folder exists.
- `items.json` has at least one item when network access succeeds.
- `index.md` links to markdown article files.
- Article markdown files contain source URL, title, date, summary, extracted text, and image reference.

## Success Criteria

- One command creates an agent-readable date-range folder.
- Existing RSS and Telegram ingestion still works.
- GDELT, Google News RSS, and Hacker News are no-signup inputs.
- Full article extraction is attempted for every article URL.
- Main article images are saved or linked.
- Bad URLs fail item-by-item, not run-wide.
- The final bundle is useful without opening the database or API UI.
