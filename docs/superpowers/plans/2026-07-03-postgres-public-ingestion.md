# Postgres Public Ingestion Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Historical note: this plan was written while the legacy `ai-news-agent/` Streamlit MVP still existed. The legacy app has since been removed; the active project is the `backend/` FastAPI/PostgreSQL service.

**Goal:** Build a Dockerized FastAPI/PostgreSQL backend that ingests public RSS feeds and public Telegram channel pages, captures images/media, and stores normalized source material for a future post-generation agent.

**Architecture:** Add a new `backend/` service beside the existing `ai-news-agent/` Streamlit MVP. The backend separates raw source observations from deduplicated content items, stores media as first-class records, and runs ingestion through an explicit worker/CLI rather than Streamlit state.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async ORM, Alembic, PostgreSQL 18, asyncpg, httpx with SOCKS proxy support, feedparser, BeautifulSoup/lxml, Pydantic Settings, pytest, Docker Compose.

---

## Context

Current repo shape:

- Existing ingestion is centralized in `ai-news-agent/agent.py`.
- RSS parsing in `ai-news-agent/connectors.py` only returns title/link/date/summary and misses most feed media fields.
- Telegram ingestion in `ai-news-agent/telegram_connector.py` uses Telethon sessions. That is not needed for public channels available at `https://t.me/s/<channel>`.
- SQLite storage in `ai-news-agent/storage.py` is review-oriented and dedupes by `url UNIQUE`, which is too weak for source provenance, media, reposts, RSS GUIDs, and later post generation.

Important live checks from July 3, 2026:

- Public Telegram page `https://t.me/s/iran_jahan_darlahze` fetched successfully through local SOCKS proxy `127.0.0.1:10808`.
- That page exposed 20 message blocks, `data-post` IDs, public permalinks, timestamps, views, text blocks, reactions, and photo markers.
- Feed validation found 50 suitable seed feeds across AI, tech, economy, and Farsi/Iranian news.
- Some feeds are blocked, stale, or HTML-only; the source schema must store fetch diagnostics and source-specific normalization profile data.

Current-source evidence:

- `ai-news-agent/connectors.py:95` has shallow RSS parsing.
- `ai-news-agent/telegram_connector.py:93` requires Telegram API credentials/session files.
- `ai-news-agent/storage.py:36` stores one `articles` table row per URL.

## Current Docs/Version Evidence

- Python.org lists Python 3.14.6 as the current 3.14 maintenance release, released June 10, 2026.
- PostgreSQL.org lists PostgreSQL 18 as the latest stable major release and also exposes PostgreSQL 19 preview/beta material; use PostgreSQL 18 for this build.
- Context7 resolved current documentation for `/fastapi/fastapi`, `/websites/sqlalchemy_en_20`, and `/websites/alembic_sqlalchemy`.
- Context7 FastAPI docs recommend `lifespan` over legacy startup/shutdown events.
- Context7 SQLAlchemy docs show SQLAlchemy 2 async usage with `create_async_engine`, `async_sessionmaker`, `AsyncAttrs`, `DeclarativeBase`, `Mapped`, and `mapped_column`.
- Context7 Alembic docs cover `alembic revision --autogenerate`.

## Target File Structure

Create:

```text
backend/
  Dockerfile
  pyproject.toml
  alembic.ini
  app/
    __init__.py
    main.py
    worker.py
    core/
      __init__.py
      config.py
      logging.py
    db/
      __init__.py
      base.py
      models.py
      session.py
    api/
      __init__.py
      routes.py
      schemas.py
    sources/
      __init__.py
      base.py
      registry.py
      rss.py
      telegram_public.py
    normalization/
      __init__.py
      dates.py
      fingerprints.py
      media.py
      text.py
      urls.py
    ingestion/
      __init__.py
      service.py
      repository.py
      seed_sources.py
    media/
      __init__.py
      downloader.py
    tests/
      conftest.py
      fixtures/
        rss_google_ai.xml
        telegram_public_sample.html
      test_rss_parser.py
      test_telegram_public_parser.py
      test_normalization.py
      test_repository.py
      test_api.py
  alembic/
    env.py
    script.py.mako
    versions/
docs/
  ingestion-source-catalog.md
docker-compose.yml
.dockerignore
```

Modify:

```text
.gitignore
README.md
ai-news-agent/README.md
```

Keep unchanged in the first backend build:

```text
ai-news-agent/app.py
ai-news-agent/agent.py
ai-news-agent/storage.py
ai-news-agent/telegram_connector.py
```

The Streamlit app was a legacy review MVP while this plan was written. It has since been removed after backend ingestion work moved into `backend/`.

## Data Model

Use UUID primary keys. Store timestamps as `timestamptz`. Use JSONB for raw metadata and parser diagnostics.

### `sources`

One row per configured source.

Fields:

```text
id uuid primary key
platform text not null
name text not null
feed_url text
homepage_url text
telegram_username text
source_group text not null
language_hint text
default_timezone text not null default 'UTC'
normalization_profile jsonb not null default '{}'
fetch_interval_minutes integer not null default 1440
etag text
last_modified text
active boolean not null default true
last_fetch_at timestamptz
created_at timestamptz not null
updated_at timestamptz not null
```

Allowed platforms for this plan:

```text
rss
atom
telegram_public
```

### `ingest_runs`

One row per manual or scheduled ingestion run.

Fields:

```text
id uuid primary key
started_at timestamptz not null
finished_at timestamptz
trigger text not null
parser_version text not null
status text not null
stats jsonb not null default '{}'
error text
```

Allowed statuses:

```text
running
succeeded
partial
failed
```

### `raw_payloads`

Raw source responses and parser evidence.

Fields:

```text
id uuid primary key
run_id uuid references ingest_runs(id)
source_id uuid references sources(id)
payload_kind text not null
request_url text not null
final_url text
http_status integer
headers jsonb not null default '{}'
content_type text
body_sha256 text
raw_text text
parser_warnings jsonb not null default '[]'
captured_at timestamptz not null
```

Allowed payload kinds:

```text
feed_xml
feed_entry
telegram_html
telegram_message_html
article_html
og_meta
media_probe
```

### `source_items`

One source occurrence per feed entry or Telegram post.

Fields:

```text
id uuid primary key
source_id uuid references sources(id)
run_id uuid references ingest_runs(id)
content_item_id uuid references content_items(id)
raw_payload_id uuid references raw_payloads(id)
external_id_raw text
external_id_norm text
source_url text
source_url_norm text
canonical_url_candidate text
title_raw text
summary_raw text
content_html_raw text
content_text_raw text
author_raw text
categories text[] not null default '{}'
published_raw text
parser_meta jsonb not null default '{}'
first_seen_at timestamptz not null
last_seen_at timestamptz not null
```

Add source-scoped unique indexes for strong source identities:

```sql
CREATE UNIQUE INDEX uq_source_item_external
ON source_items (source_id, external_id_norm)
WHERE external_id_norm IS NOT NULL;

CREATE INDEX ix_source_items_seen
ON source_items (source_id, last_seen_at DESC);
```

### `content_items`

Deduplicated content row used by the future posting agent.

Fields:

```text
id uuid primary key
item_type text not null
canonical_url text
canonical_url_hash text
title text
title_fingerprint text
summary text
content_text text
content_html_sanitized text
language_code text
script_code text
direction text
authors jsonb not null default '[]'
tags text[] not null default '{}'
published_at timestamptz
source_updated_at timestamptz
sort_at timestamptz not null
date_raw text
date_source text
date_parse_status text not null
primary_source_id uuid references sources(id)
primary_image_id uuid
status text not null default 'new'
score integer not null default 0
metrics jsonb not null default '{}'
duplicate_of_id uuid references content_items(id)
first_seen_at timestamptz not null
last_seen_at timestamptz not null
created_at timestamptz not null
updated_at timestamptz not null
```

Allowed item types:

```text
article
telegram_post
video
audio
document
```

Allowed content statuses:

```text
new
ready_for_agent
ignored
duplicate
error
```

### `item_identities`

Strong and weak dedupe identities.

Fields:

```text
id uuid primary key
content_item_id uuid references content_items(id)
source_item_id uuid references source_items(id)
identity_type text not null
identity_value text not null
identity_hash text not null
scope text not null
source_id uuid references sources(id)
confidence numeric not null
is_strong boolean not null
created_at timestamptz not null
```

Identity types:

```text
rss_guid
atom_id
telegram_post
normalized_url
canonical_url
content_hash
title_date_fingerprint
```

Indexes:

```sql
CREATE UNIQUE INDEX uq_identity_global_strong
ON item_identities (identity_type, identity_hash)
WHERE scope = 'global' AND is_strong;

CREATE UNIQUE INDEX uq_identity_source_strong
ON item_identities (source_id, identity_type, identity_hash)
WHERE scope = 'source' AND is_strong;
```

### `media_assets`

One row per image, video, audio, or document candidate.

Fields:

```text
id uuid primary key
original_url text not null
normalized_url text not null
url_hash text not null
kind text not null
mime_type text
width integer
height integer
duration_seconds numeric
byte_length bigint
alt_text text
title text
source_field text not null
checksum_sha256 text
storage_path text
fetch_status text not null
raw_metadata jsonb not null default '{}'
created_at timestamptz not null
updated_at timestamptz not null
```

Allowed media kinds:

```text
image
video
audio
document
```

Allowed fetch statuses:

```text
remote_only
downloaded
failed
skipped
```

### `item_media`

Join table between content items and media assets.

Fields:

```text
content_item_id uuid references content_items(id)
media_asset_id uuid references media_assets(id)
role text not null
sort_order integer not null default 0
confidence numeric not null default 1.0
extracted_from text not null
primary key (content_item_id, media_asset_id, role)
```

Allowed roles:

```text
primary_image
thumbnail
inline_image
enclosure
attachment
avatar
```

## Algorithmic RSS Design

### Fetching

1. Load active `sources` where `platform in ('rss', 'atom')`.
2. Use `httpx.AsyncClient` with:
   - default timeout 20 seconds
   - retry wrapper with 2 retries
   - `User-Agent: NewsCraftBot/1.0`
   - optional `ALL_PROXY` or `HTTP_PROXY`/`HTTPS_PROXY`
   - `If-None-Match` from `sources.etag`
   - `If-Modified-Since` from `sources.last_modified`
3. Store every response in `raw_payloads` before parsing.
4. Treat HTTP 304 as success with zero new items and update run stats.
5. Save new `ETag` and `Last-Modified` back to `sources`.

### Feed Type Detection

Use `feedparser` first because it handles malformed real-world feeds. Also keep raw XML text for audit.

Detection rules:

```text
feed.version starts with 'rss' -> platform rss
feed.version starts with 'atom' -> platform atom
no version but entries exist -> rss-compatible degraded parser
no entries -> source fetch succeeded but parser status failed
```

### Entry Field Priority

Title:

```text
entry.title
entry.get('title_detail').value
first non-empty line from summary/content
```

External ID:

```text
entry.id
entry.guid
entry.link
sha256(source_id + normalized_title + normalized_published_raw)
```

URL:

```text
entry.link
entry.links where rel == 'alternate'
entry.id if guid is permalink URL
```

Text:

```text
entry.content[0].value
entry.summary
entry.description
title
```

Date:

```text
entry.published
entry.updated
entry.created
entry.published_parsed
entry.updated_parsed
fallback first_seen_at
```

Author:

```text
entry.author
entry.authors[].name
feed.feed.author
```

Tags:

```text
entry.tags[].term
entry.category
source.source_group
```

### Media Extraction Priority

Extract all media candidates, then rank primary image:

```text
1. media:content image
2. media:thumbnail
3. enclosure with image/* MIME type
4. Atom link rel=enclosure with image/* MIME type
5. inline img tags in content/summary
6. article page og:image
7. article page twitter:image
8. source default image from normalization_profile.default_image_url
```

Keep every valid media candidate in `media_assets`; do not throw away lower-priority media because the future post agent may need alternatives.

Reject:

```text
1x1 tracking pixels
SVG icons smaller than 64px
same-domain logo paths when normalization_profile.reject_logo_images is true
empty URLs
non-http URLs
```

### URL and Identity Normalization

URL normalization:

```text
lowercase scheme and host
remove fragment
remove tracking params: utm_*, fbclid, gclid, mc_cid, mc_eid, cmpid, ref
sort query parameters
resolve relative URLs against feed URL
normalize trailing slash only when path is not root
```

Identity build order:

```text
canonical_url global strong
normalized_url global strong
telegram_post global strong
rss_guid source strong when GUID is non-empty
atom_id source strong
content_hash global strong when content_text length >= 80
title_date_fingerprint source weak
```

Dedupe order:

```text
strong canonical_url
strong normalized_url
strong source GUID/Atom ID
strong content_hash
weak title_date_fingerprint
```

Weak matches must not auto-merge across unrelated sources. They may set `duplicate_of_id` only when the date is within 48 hours and the fingerprint similarity is high.

### Persian/Arabic Text Handling

Display text stays untouched. Fingerprints use a normalized copy:

```text
Unicode NFKC
map Arabic ي to Persian ی
map Arabic ك to Persian ک
remove tatweel
remove Arabic diacritics
normalize repeated whitespace
preserve ZWNJ in display text, normalize it for fingerprints
```

Set:

```text
direction = 'rtl' when Arabic script dominates
script_code = 'Arab' for Persian/Arabic-script text
language_code = sources.language_hint when detection confidence is low
```

## Public Telegram Design

### Fetching

For public channels, use:

```text
https://t.me/s/<telegram_username>
```

Use the same `httpx.AsyncClient` proxy/timeout/retry layer as RSS.

### Parsing

Parse static HTML message blocks:

```text
.tgme_widget_message
data-post="<channel>/<message_id>"
.tgme_widget_message_text
.tgme_widget_message_date time[datetime]
.tgme_widget_message_views
.tgme_widget_message_photo
.tgme_widget_message_video
.tgme_widget_message_document
.tgme_widget_message_link_preview
```

Extract:

```text
external_id_norm = channel + '/' + message_id
source_url = https://t.me/<channel>/<message_id>
title = first non-empty text line, capped at 160 chars
content_text = cleaned message text
published_at = time datetime
metrics.views = parsed view count
metrics.reactions = parsed reaction counts
media candidates from message photo/video/document blocks
link preview media and URL when present
```

Do not store channel avatars as item media. Only media inside the message bubble counts.

## Seed Source Catalog

Seed these 50 feeds in `backend/app/ingestion/seed_sources.py`. The seed script must be idempotent by platform + feed URL.

| # | Name | Group | Lang | Feed URL | Media Strategy |
|---:|---|---|---|---|---|
| 1 | OpenAI News | ai | en | https://openai.com/news/rss.xml | RSS first, OG image fallback |
| 2 | Google AI Blog | ai | en | https://blog.google/technology/ai/rss/ | media tags |
| 3 | Hugging Face Blog | ai | en | https://huggingface.co/blog/feed.xml | OG fallback |
| 4 | MIT Technology Review AI | ai | en | https://www.technologyreview.com/topic/artificial-intelligence/feed/ | OG fallback |
| 5 | VentureBeat AI | ai | en | https://venturebeat.com/category/ai/feed/ | media tags |
| 6 | The Verge AI | ai | en | https://www.theverge.com/rss/ai-artificial-intelligence/index.xml | OG fallback |
| 7 | TechCrunch AI | ai | en | https://techcrunch.com/category/artificial-intelligence/feed/ | OG fallback |
| 8 | The Gradient | ai | en | https://thegradient.pub/rss/ | media tags |
| 9 | BAIR Blog | ai | en | https://bair.berkeley.edu/blog/feed.xml | media tags |
| 10 | Google Research Blog | ai | en | https://research.google/blog/rss/ | media tags |
| 11 | AWS Machine Learning Blog | ai | en | https://aws.amazon.com/blogs/machine-learning/feed/ | media tags |
| 12 | NVIDIA Blog | ai | en | https://blogs.nvidia.com/feed/ | media tags |
| 13 | Microsoft Research Blog | ai | en | https://www.microsoft.com/en-us/research/feed/ | media tags |
| 14 | IEEE Spectrum AI | ai | en | https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss | media tags |
| 15 | The Decoder | ai | en | https://the-decoder.com/feed/ | media tags |
| 16 | TechCrunch | tech | en | https://techcrunch.com/feed/ | OG fallback |
| 17 | The Verge | tech | en | https://www.theverge.com/rss/index.xml | OG fallback |
| 18 | Ars Technica | tech | en | https://feeds.arstechnica.com/arstechnica/index | media tags |
| 19 | WIRED | tech | en | https://www.wired.com/feed/rss | media tags |
| 20 | Engadget | tech | en | https://www.engadget.com/rss.xml | media tags |
| 21 | ZDNET | tech | en | https://www.zdnet.com/news/rss.xml | OG fallback |
| 22 | InfoQ | tech | en | https://feed.infoq.com/ | media tags |
| 23 | Hacker News | tech | en | https://news.ycombinator.com/rss | no media expected |
| 24 | Y Combinator Blog | tech | en | https://www.ycombinator.com/blog/rss | media tags |
| 25 | GitHub Blog | tech | en | https://github.blog/feed/ | media tags |
| 26 | Stack Overflow Blog | tech | en | https://stackoverflow.blog/feed/ | OG fallback |
| 27 | Cloudflare Blog | tech | en | https://blog.cloudflare.com/rss/ | media tags |
| 28 | Federal Reserve Press | economy | en | https://www.federalreserve.gov/feeds/press_all.xml | no media expected |
| 29 | US Treasury | economy | en | https://home.treasury.gov/rss.xml | no media expected |
| 30 | SEC Press Releases | economy | en | https://www.sec.gov/news/pressreleases.rss | no media expected |
| 31 | BEA | economy | en | https://apps.bea.gov/rss/rss.xml | no media expected |
| 32 | ECB Latest Releases | economy | en | https://www.ecb.europa.eu/rss/press.html | no media expected |
| 33 | Bank of England News | economy | en | https://www.bankofengland.co.uk/rss/news | no media expected |
| 34 | BIS Press Releases | economy | en | https://www.bis.org/doclist/all_pressrels.rss | no media expected |
| 35 | FRED Blog | economy | en | https://fredblog.stlouisfed.org/feed/ | inline chart images |
| 36 | NY Fed Liberty Street Economics | economy | en | https://libertystreeteconomics.newyorkfed.org/feed/ | inline chart images |
| 37 | FT Markets | economy | en | https://www.ft.com/markets?format=rss | OG fallback |
| 38 | CNBC Economy | economy | en | https://www.cnbc.com/id/20910258/device/rss/rss.html | OG fallback |
| 39 | MarketWatch Top Stories | economy | en | https://feeds.content.dowjones.io/public/rss/mw_topstories | media tags |
| 40 | Yahoo Finance | economy | en | https://finance.yahoo.com/news/rss | media tags |
| 41 | Investing.com News | economy | en | https://www.investing.com/rss/news.rss | image enclosures |
| 42 | IRNA | farsi_news | fa | https://www.irna.ir/rss | media tags |
| 43 | ISNA | farsi_news | fa | https://www.isna.ir/rss | media tags |
| 44 | Mehr News | farsi_news | fa | https://www.mehrnews.com/rss | media tags |
| 45 | Tasnim | farsi_news | fa | https://tasnimnews.ir/fa/rss/feed/0/8/0/%D9%85%D9%87%D9%85%D8%AA%D8%B1%DB%8C%D9%86-%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1-%D8%AA%D8%B3%D9%86%DB%8C%D9%85 | media tags |
| 46 | KhabarOnline | farsi_news | fa | https://www.khabaronline.ir/rss | media tags |
| 47 | Hamshahri Online | farsi_news | fa | https://www.hamshahrionline.ir/rss | media tags |
| 48 | Mashregh News | farsi_news | fa | https://www.mashreghnews.ir/rss | media tags |
| 49 | Donya-e-Eqtesad | farsi_economy | fa | https://donya-e-eqtesad.com/rss | media tags |
| 50 | Zoomit | farsi_tech | fa | https://www.zoomit.ir/feed/ | media tags |

Secondary feeds to keep documented but not enabled in the initial seed:

```text
Digiato: https://digiato.com/feed
Peivast: https://peivast.com/feed
Way2Pay: https://way2pay.ir/feed/
IRIB News: https://www.iribnews.ir/fa/rss/allnews
Asr Iran: https://www.asriran.com/fa/rss/allnews
Tabnak: https://www.tabnak.ir/fa/rss/allnews
Krebs on Security: https://krebsonsecurity.com/feed/
Dark Reading: https://www.darkreading.com/rss.xml
The Register: https://www.theregister.com/headlines.atom
Tom's Hardware: https://www.tomshardware.com/feeds/all
```

Feeds deliberately excluded from the initial seed:

```text
Reuters legacy RSS: unresolved/stale in checks
WSJ section feeds: stale January 2025 items in checks
Old Microsoft AI blog feed: Cloudflare/blocking in checks
Old NVIDIA AI category feed: failed in checks; use blogs.nvidia.com/feed instead
BLS/Census: valuable but blocked from current host; add when fetch policy is confirmed
```

## Implementation Tasks

### Task 1: Backend Project Skeleton

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing smoke test**

Create `backend/tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Create project dependencies**

Create `backend/pyproject.toml`:

```toml
[project]
name = "newscraft-backend"
version = "0.1.0"
description = "PostgreSQL-backed ingestion backend for NewsCraft"
requires-python = ">=3.14"
dependencies = [
  "alembic>=1.16",
  "asyncpg>=0.30",
  "beautifulsoup4>=4.13",
  "fastapi>=0.128",
  "feedparser>=6.0",
  "httpx[socks]>=0.28",
  "lxml>=6.0",
  "pydantic-settings>=2.10",
  "python-dateutil>=2.9",
  "sqlalchemy>=2.0",
  "uvicorn[standard]>=0.35",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.4",
  "pytest-asyncio>=1.0",
  "ruff>=0.13",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 120
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 3: Create settings and app entry point**

Create `backend/app/core/config.py`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NewsCraft Backend"
    database_url: str = Field(default="postgresql+asyncpg://newscraft:newscraft@postgres:5432/newscraft")
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    media_root: str = "/data/media"
    parser_version: str = "2026-07-03-public-ingestion-v1"


settings = Settings()
```

Create `backend/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="NewsCraft Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run the smoke test**

Run:

```bash
cd backend
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app backend/tests/test_api.py
git commit -m "feat: add backend FastAPI skeleton"
```

### Task 2: SQLAlchemy Models and Alembic Migration

**Files:**
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/models.py`
- Create: `backend/app/db/session.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial_ingestion_schema.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write model metadata test**

Create `backend/tests/test_models.py`:

```python
from app.db.models import Base


def test_ingestion_tables_are_registered():
    expected = {
        "sources",
        "ingest_runs",
        "raw_payloads",
        "source_items",
        "content_items",
        "item_identities",
        "media_assets",
        "item_media",
    }

    assert expected.issubset(set(Base.metadata.tables))
```

- [ ] **Step 2: Add base/session files**

Create `backend/app/db/base.py`:

```python
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    pass
```

Create `backend/app/db/session.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
```

- [ ] **Step 3: Implement models**

Create `backend/app/db/models.py` with the tables defined in the Data Model section. Use SQLAlchemy 2 typed models:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    feed_url: Mapped[str | None] = mapped_column(Text)
    homepage_url: Mapped[str | None] = mapped_column(Text)
    telegram_username: Mapped[str | None] = mapped_column(Text)
    source_group: Mapped[str] = mapped_column(Text, nullable=False)
    language_hint: Mapped[str | None] = mapped_column(Text)
    default_timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    normalization_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1440")
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_fetch_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("platform", "feed_url", name="uq_sources_platform_feed_url"),
        UniqueConstraint("platform", "telegram_username", name="uq_sources_platform_telegram_username"),
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None]
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
```

Continue the same file with `RawPayload`, `SourceItem`, `ContentItem`, `ItemIdentity`, `MediaAsset`, and `ItemMedia` exactly matching the Data Model section. Include relationships where they help tests and repository code; avoid lazy-loading in ingestion paths.

- [ ] **Step 4: Add migration file**

Create `backend/alembic/versions/0001_initial_ingestion_schema.py` with Alembic `op.create_table` calls matching the model columns and indexes. Include:

```python
revision = "0001_initial_ingestion_schema"
down_revision = None
branch_labels = None
depends_on = None
```

The upgrade must create all eight tables. The downgrade must drop tables in reverse dependency order:

```text
item_media
media_assets
item_identities
source_items
content_items
raw_payloads
ingest_runs
sources
```

- [ ] **Step 5: Run tests and migration check**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_models.py -q
.venv/bin/alembic upgrade head
```

Expected:

```text
1 passed
Running upgrade  -> 0001_initial_ingestion_schema
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/db backend/alembic.ini backend/alembic backend/tests/test_models.py
git commit -m "feat: add Postgres ingestion schema"
```

### Task 3: Normalization Utilities

**Files:**
- Create: `backend/app/normalization/urls.py`
- Create: `backend/app/normalization/text.py`
- Create: `backend/app/normalization/dates.py`
- Create: `backend/app/normalization/fingerprints.py`
- Test: `backend/tests/test_normalization.py`

- [ ] **Step 1: Write failing normalization tests**

Create `backend/tests/test_normalization.py`:

```python
from datetime import timezone

from app.normalization.dates import parse_source_datetime
from app.normalization.fingerprints import content_hash, title_date_fingerprint
from app.normalization.text import fingerprint_text, infer_direction
from app.normalization.urls import normalize_url


def test_normalize_url_removes_tracking_and_fragment():
    assert normalize_url("HTTPS://Example.com/a?utm_source=x&b=2&a=1#frag") == "https://example.com/a?a=1&b=2"


def test_persian_fingerprint_normalizes_arabic_variants():
    assert fingerprint_text("علي كاظمي") == fingerprint_text("علی کاظمی")
    assert infer_direction("خبر فوری درباره اقتصاد ایران") == "rtl"


def test_parse_source_datetime_uses_default_timezone():
    parsed, status = parse_source_datetime("10 May 2026 14:39:34", default_timezone="Asia/Tehran")

    assert parsed.tzinfo == timezone.utc
    assert status == "assumed_timezone"


def test_hashes_are_stable():
    assert content_hash("Hello   World") == content_hash("hello world")
    assert title_date_fingerprint("AI News", "2026-07-03") == title_date_fingerprint("ai news", "2026-07-03")
```

- [ ] **Step 2: Implement URL normalization**

Create `backend/app/normalization/urls.py`:

```python
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "cmpid", "ref"}


def normalize_url(url: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url, url.strip()) if base_url else url.strip()
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in TRACKING_PARAMS or any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((scheme, host, path, query, ""))


def hash_value(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
```

- [ ] **Step 3: Implement text/date/fingerprint helpers**

Create the remaining normalization files to satisfy the tests. Use `dateutil.parser.parse`, `zoneinfo.ZoneInfo`, `unicodedata.normalize`, and SHA-256 hashing. Preserve display text in parser outputs; only normalize fingerprint strings.

- [ ] **Step 4: Run tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_normalization.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/normalization backend/tests/test_normalization.py
git commit -m "feat: add ingestion normalization helpers"
```

### Task 4: RSS Parser with Media Extraction

**Files:**
- Create: `backend/app/sources/base.py`
- Create: `backend/app/sources/rss.py`
- Create: `backend/app/normalization/media.py`
- Create: `backend/tests/fixtures/rss_google_ai.xml`
- Test: `backend/tests/test_rss_parser.py`

- [ ] **Step 1: Capture fixture**

Use a small real feed excerpt from `https://blog.google/technology/ai/rss/` with one item containing `media:content`. Save it to `backend/tests/fixtures/rss_google_ai.xml`.

- [ ] **Step 2: Write failing parser tests**

Create `backend/tests/test_rss_parser.py`:

```python
from pathlib import Path

from app.sources.rss import parse_rss_feed


def test_rss_parser_extracts_items_and_media():
    xml = Path("tests/fixtures/rss_google_ai.xml").read_text(encoding="utf-8")

    parsed = parse_rss_feed(
        xml,
        source_name="Google AI Blog",
        source_url="https://blog.google/technology/ai/rss/",
        default_timezone="UTC",
    )

    assert parsed.items
    first = parsed.items[0]
    assert first.title
    assert first.external_id_norm
    assert first.source_url_norm.startswith("https://")
    assert first.media_candidates
    assert first.media_candidates[0].kind == "image"
```

- [ ] **Step 3: Implement typed parser outputs**

Create `backend/app/sources/base.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MediaCandidate:
    original_url: str
    normalized_url: str
    kind: str
    source_field: str
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    title: str | None = None
    confidence: float = 1.0


@dataclass(slots=True)
class ParsedSourceItem:
    external_id_raw: str | None
    external_id_norm: str
    source_url: str | None
    source_url_norm: str | None
    canonical_url_candidate: str | None
    title: str
    summary: str
    content_html: str | None
    content_text: str
    author: str | None
    categories: list[str]
    published_raw: str | None
    published_at: datetime | None
    date_parse_status: str
    media_candidates: list[MediaCandidate] = field(default_factory=list)
    parser_meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class ParsedSourcePayload:
    items: list[ParsedSourceItem]
    warnings: list[str] = field(default_factory=list)
    feed_meta: dict = field(default_factory=dict)
```

- [ ] **Step 4: Implement RSS parsing**

Create `backend/app/sources/rss.py`. It must:

```text
use feedparser.parse
extract title/link/id/guid/summary/content/author/tags/date
call normalize_url for item links and media URLs
extract media:content, media:thumbnail, enclosures, Atom enclosures, and inline img tags
return ParsedSourcePayload
record warnings for bozo feeds and missing title/link/date
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_rss_parser.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/sources/base.py backend/app/sources/rss.py backend/app/normalization/media.py backend/tests/fixtures/rss_google_ai.xml backend/tests/test_rss_parser.py
git commit -m "feat: parse RSS feeds with media candidates"
```

### Task 5: Public Telegram Parser

**Files:**
- Create: `backend/app/sources/telegram_public.py`
- Create: `backend/tests/fixtures/telegram_public_sample.html`
- Test: `backend/tests/test_telegram_public_parser.py`

- [ ] **Step 1: Capture fixture**

Fetch through the local proxy and store a trimmed fixture with 2 message blocks:

```bash
curl --socks5-hostname 127.0.0.1:10808 -L -A 'Mozilla/5.0' \
  'https://t.me/s/iran_jahan_darlahze' \
  -o /tmp/telegram_public_sample.html
```

Trim two `.tgme_widget_message` blocks into `backend/tests/fixtures/telegram_public_sample.html`.

- [ ] **Step 2: Write failing parser test**

Create `backend/tests/test_telegram_public_parser.py`:

```python
from pathlib import Path

from app.sources.telegram_public import parse_public_telegram_page


def test_public_telegram_parser_extracts_posts_and_images():
    html = Path("tests/fixtures/telegram_public_sample.html").read_text(encoding="utf-8")

    parsed = parse_public_telegram_page(html, channel="iran_jahan_darlahze")

    assert parsed.items
    first = parsed.items[0]
    assert first.external_id_norm.startswith("iran_jahan_darlahze/")
    assert first.source_url_norm.startswith("https://t.me/iran_jahan_darlahze/")
    assert first.content_text
    assert "views" in first.parser_meta
    assert all(candidate.source_field != "channel_avatar" for candidate in first.media_candidates)
```

- [ ] **Step 3: Implement parser**

Create `backend/app/sources/telegram_public.py`. It must:

```text
parse .tgme_widget_message blocks with BeautifulSoup
read data-post and split channel/message_id
extract .js-message_text text with newlines preserved
extract time datetime
parse views like 32.7K to integer 32700
extract reactions into parser_meta.reactions
extract message photo/video/document/link preview media
ignore .tgme_widget_message_user_photo channel avatars
return ParsedSourcePayload
```

- [ ] **Step 4: Run tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_telegram_public_parser.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/sources/telegram_public.py backend/tests/fixtures/telegram_public_sample.html backend/tests/test_telegram_public_parser.py
git commit -m "feat: parse public Telegram channel pages"
```

### Task 6: Repository Upsert and Dedupe

**Files:**
- Create: `backend/app/ingestion/repository.py`
- Test: `backend/tests/test_repository.py`

- [ ] **Step 1: Write repository tests**

Create `backend/tests/test_repository.py` with async tests that verify:

```text
same RSS GUID on same source updates one source_item
same canonical URL across two sources links to one content_item
same Telegram channel/message_id is idempotent
two media candidates attach to one content item with primary_image first
weak title/date fingerprint does not merge across different sources without strong identity
```

- [ ] **Step 2: Implement repository methods**

Create `backend/app/ingestion/repository.py` with an `IngestionRepository` class that exposes these public methods:

```text
create_run(trigger: str, parser_version: str) -> IngestRun
finish_run(run_id: UUID, status: str, stats: dict, error: str | None = None) -> None
get_active_sources(platforms: list[str] | None = None) -> list[Source]
save_raw_payload(run_id: UUID, source_id: UUID, payload_kind: str, request_url: str, final_url: str | None, http_status: int | None, headers: dict, content_type: str | None, raw_text: str, parser_warnings: list[str]) -> RawPayload
upsert_source_item(run_id: UUID, source_id: UUID, raw_payload_id: UUID, parsed_item: ParsedSourceItem) -> SourceItem
find_content_item_by_identities(identities: list[dict]) -> ContentItem | None
upsert_content_item(source: Source, source_item: SourceItem, parsed_item: ParsedSourceItem, identities: list[dict]) -> ContentItem
attach_identities(content_item_id: UUID, source_item_id: UUID, source_id: UUID, identities: list[dict]) -> None
upsert_media_assets(parsed_item: ParsedSourceItem) -> list[MediaAsset]
attach_item_media(content_item_id: UUID, media_assets: list[MediaAsset], parsed_item: ParsedSourceItem) -> None
```

Use Postgres `ON CONFLICT` where it keeps logic clearer. Keep all repository writes inside caller-owned transactions.

- [ ] **Step 3: Run repository tests**

Run:

```bash
cd backend
docker compose up -d postgres
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest tests/test_repository.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/ingestion/repository.py backend/tests/test_repository.py
git commit -m "feat: add ingestion repository upserts"
```

### Task 7: Source Seed Catalog

**Files:**
- Create: `backend/app/ingestion/seed_sources.py`
- Create: `docs/ingestion-source-catalog.md`
- Test: `backend/tests/test_seed_sources.py`

- [ ] **Step 1: Write seed catalog tests**

Create `backend/tests/test_seed_sources.py`:

```python
from app.ingestion.seed_sources import SEED_SOURCES


def test_seed_catalog_has_50_active_sources():
    assert len(SEED_SOURCES) == 50
    assert all(source["active"] for source in SEED_SOURCES)
    assert {source["language_hint"] for source in SEED_SOURCES} >= {"en", "fa"}


def test_seed_catalog_has_expected_groups():
    groups = {source["source_group"] for source in SEED_SOURCES}

    assert {"ai", "tech", "economy", "farsi_news", "farsi_economy", "farsi_tech"}.issubset(groups)
```

- [ ] **Step 2: Implement `SEED_SOURCES`**

Create `backend/app/ingestion/seed_sources.py` with the 50 rows from the Seed Source Catalog section. Each dict must include:

```python
{
    "platform": "rss",
    "name": "OpenAI News",
    "feed_url": "https://openai.com/news/rss.xml",
    "homepage_url": "https://openai.com/news/",
    "source_group": "ai",
    "language_hint": "en",
    "default_timezone": "UTC",
    "active": True,
    "normalization_profile": {"media_strategy": "og_fallback"},
}
```

Use `platform = "atom"` only for Atom feeds such as `https://www.theregister.com/headlines.atom` when they are added as secondary sources.

- [ ] **Step 3: Add seed command**

Implement `seed_sources(session: AsyncSession) -> int`. It must iterate through `SEED_SOURCES`, execute one upsert per source, and return the number of rows inserted or updated.

The function must upsert by `(platform, feed_url)` for RSS/Atom and `(platform, telegram_username)` for Telegram.

- [ ] **Step 4: Document the catalog**

Create `docs/ingestion-source-catalog.md` with:

```text
validated date: 2026-07-03
validation method: curl/feed parsing with local SOCKS proxy when needed
50 active seed feeds
secondary candidate feeds
excluded feeds and reason
```

- [ ] **Step 5: Run seed tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_seed_sources.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/seed_sources.py backend/tests/test_seed_sources.py docs/ingestion-source-catalog.md
git commit -m "feat: add validated ingestion source catalog"
```

### Task 8: Ingestion Service and Worker CLI

**Files:**
- Create: `backend/app/ingestion/service.py`
- Create: `backend/app/sources/registry.py`
- Create: `backend/app/worker.py`
- Test: `backend/tests/test_ingestion_service.py`

- [ ] **Step 1: Write service tests**

Create `backend/tests/test_ingestion_service.py` with mocked HTTP responses and repository fakes. Assert:

```text
RSS source fetch stores raw payload before parsing
Telegram public source uses t.me/s/<channel>
HTTP 304 marks source skipped without parser failure
source fetch error produces partial run status
media candidates are sent to repository
```

- [ ] **Step 2: Implement source registry**

Create `backend/app/sources/registry.py`:

```python
from app.db.models import Source
from app.sources.rss import parse_rss_feed
from app.sources.telegram_public import parse_public_telegram_page


def parser_for_source(source: Source):
    if source.platform in {"rss", "atom"}:
        return parse_rss_feed
    if source.platform == "telegram_public":
        return parse_public_telegram_page
    raise ValueError(f"Unsupported source platform: {source.platform}")
```

- [ ] **Step 3: Implement ingestion service**

Create `backend/app/ingestion/service.py` with an `IngestionService` class exposing `run_once(platforms: list[str] | None = None, source_ids: list[str] | None = None, trigger: str = "manual") -> dict`.

The service must:

```text
create ingest_run(status=running)
load active sources
fetch each source with conditional headers
store raw payload
parse source payload
call repository upserts for source_items, content_items, identities, media
update source etag/last_modified/last_fetch_at
finish run as succeeded/partial/failed
return stats dict
```

- [ ] **Step 4: Implement worker CLI**

Create `backend/app/worker.py`:

```python
import argparse
import asyncio

from app.db.session import async_session
from app.ingestion.service import IngestionService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", action="append", choices=["rss", "atom", "telegram_public"])
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()

    async with async_session() as session:
        service = IngestionService(session)
        stats = await service.run_once(platforms=args.platform, trigger=args.trigger)
        print(stats)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Run tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_ingestion_service.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/service.py backend/app/sources/registry.py backend/app/worker.py backend/tests/test_ingestion_service.py
git commit -m "feat: add ingestion service and worker"
```

### Task 9: Media Downloader

**Files:**
- Create: `backend/app/media/downloader.py`
- Test: `backend/tests/test_media_downloader.py`

- [ ] **Step 1: Write media downloader tests**

Create `backend/tests/test_media_downloader.py`. Assert:

```text
image response is saved under /data/media/<sha-prefix>/<sha>.<ext>
checksum is recorded
non-image content for image candidate is skipped
large response above max size is skipped
failed URL marks fetch_status failed
```

- [ ] **Step 2: Implement downloader**

Create `backend/app/media/downloader.py` with a `MediaDownloader` class exposing `download_missing(limit: int = 100) -> dict`. The return dict must include `checked`, `downloaded`, `skipped`, and `failed` integer counts.

Use:

```text
HEAD when available
GET with stream
max image size 15 MB
MIME sniff from Content-Type and file signature
SHA-256 checksum
atomic write via temporary file then rename
```

- [ ] **Step 3: Wire downloader into worker**

Add `--download-media` flag to `backend/app/worker.py`. When set, run ingestion first, then download missing media.

- [ ] **Step 4: Run tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_media_downloader.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/media/downloader.py backend/app/worker.py backend/tests/test_media_downloader.py
git commit -m "feat: download ingested media assets"
```

### Task 10: API Endpoints

**Files:**
- Create: `backend/app/api/schemas.py`
- Create: `backend/app/api/routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Extend API tests**

Update `backend/tests/test_api.py` to assert:

```text
GET /health returns ok
GET /sources returns source summaries
POST /sources/seed seeds the 50-source catalog
POST /ingest/run triggers ingestion and returns run stats
GET /content-items returns latest content with primary media
```

- [ ] **Step 2: Add schemas**

Create `backend/app/api/schemas.py` with Pydantic response models:

```text
SourceOut
MediaAssetOut
ContentItemOut
IngestRunOut
IngestRunRequest
```

- [ ] **Step 3: Add routes**

Create `backend/app/api/routes.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ContentItemOut, IngestRunRequest, IngestRunOut, SourceOut
from app.db.models import ContentItem, Source
from app.db.session import get_session
from app.ingestion.seed_sources import seed_sources
from app.ingestion.service import IngestionService

router = APIRouter()


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Source).order_by(Source.source_group, Source.name))
    return list(rows)


@router.post("/sources/seed")
async def seed(session: AsyncSession = Depends(get_session)):
    count = await seed_sources(session)
    await session.commit()
    return {"upserted": count}


@router.post("/ingest/run", response_model=IngestRunOut)
async def run_ingest(request: IngestRunRequest, session: AsyncSession = Depends(get_session)):
    service = IngestionService(session)
    stats = await service.run_once(platforms=request.platforms, source_ids=request.source_ids, trigger="api")
    return stats


@router.get("/content-items", response_model=list[ContentItemOut])
async def list_content_items(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(ContentItem).order_by(ContentItem.sort_at.desc()).limit(100))
    return list(rows)
```

- [ ] **Step 4: Include router in app**

Modify `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="NewsCraft Backend")
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Run API tests**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/test_api.py
git commit -m "feat: expose ingestion API endpoints"
```

### Task 11: Docker Compose

**Files:**
- Create: `backend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Create Dockerfile**

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -e '.[dev]'

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create Compose file**

Create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: newscraft
      POSTGRES_PASSWORD: newscraft
      POSTGRES_DB: newscraft
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U newscraft -d newscraft"]
      interval: 5s
      timeout: 5s
      retries: 20

  api:
    build:
      context: ./backend
    environment:
      DATABASE_URL: postgresql+asyncpg://newscraft:newscraft@postgres:5432/newscraft
      ALL_PROXY: ${ALL_PROXY:-}
      MEDIA_ROOT: /data/media
    ports:
      - "8000:8000"
    volumes:
      - media_data:/data/media
    depends_on:
      postgres:
        condition: service_healthy

  worker:
    build:
      context: ./backend
    command: ["python", "-m", "app.worker", "--trigger", "manual", "--download-media"]
    environment:
      DATABASE_URL: postgresql+asyncpg://newscraft:newscraft@postgres:5432/newscraft
      ALL_PROXY: ${ALL_PROXY:-}
      MEDIA_ROOT: /data/media
    volumes:
      - media_data:/data/media
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
  media_data:
```

- [ ] **Step 3: Add ignore rules**

Modify `.gitignore`:

```text
backend/.venv/
backend/.pytest_cache/
backend/.ruff_cache/
```

Create `.dockerignore`:

```text
.git
**/__pycache__/
**/.pytest_cache/
**/.ruff_cache/
**/.venv/
*.db
data/
```

- [ ] **Step 4: Run Docker verification**

Run:

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.worker --trigger manual --platform rss --download-media
curl http://localhost:8000/health
```

Expected:

```text
{"status":"ok"}
```

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile docker-compose.yml .dockerignore .gitignore README.md
git commit -m "feat: dockerize ingestion backend"
```

### Task 12: End-to-End Verification and Legacy Boundary

**Files:**
- Modify: `README.md`
- Modify: `ai-news-agent/README.md`
- Create: `docs/ingestion-backend.md`

- [ ] **Step 1: Add backend docs**

Create `docs/ingestion-backend.md` covering:

```text
why public Telegram replaces Telethon for public channels
how to use ALL_PROXY=socks5://127.0.0.1:10808
how to run migrations
how to seed sources
how to trigger ingestion
where media is stored
what the future post agent should read
```

- [ ] **Step 2: Update root README**

Add a concise section:

```markdown
## Backend Ingestion Service

The new backend service lives in `backend/`. It uses FastAPI, PostgreSQL, and a worker command to ingest RSS feeds and public Telegram channel pages. It stores raw payloads, normalized content items, and media assets for downstream post generation.
```

- [ ] **Step 3: Update legacy app README**

Add a note to `ai-news-agent/README.md`:

```markdown
The Streamlit app is the legacy review dashboard. New scheduled ingestion work should use `backend/`, not Streamlit session state.
```

- [ ] **Step 4: Run final checks**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
cd ..
docker compose build
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.worker --trigger manual --platform rss --download-media
git status --short
```

Expected:

```text
all tests pass
ruff exits 0
docker build succeeds
worker reports fetched/saved item counts
git status shows only intended docs/code changes before final commit
```

- [ ] **Step 5: Commit**

```bash
git add README.md ai-news-agent/README.md docs/ingestion-backend.md
git commit -m "docs: document ingestion backend workflow"
```

## Execution Order

1. Task 1: Backend skeleton
2. Task 2: Postgres schema
3. Task 3: Normalization utilities
4. Task 4: RSS parser
5. Task 5: Public Telegram parser
6. Task 6: Repository/dedupe
7. Task 7: Source seed catalog
8. Task 8: Ingestion service and worker
9. Task 9: Media downloader
10. Task 10: API endpoints
11. Task 11: Docker Compose
12. Task 12: End-to-end verification and docs

## Self-Review

Spec coverage:

- PostgreSQL backend: Tasks 2, 6, 10, 11.
- Public Telegram without Telethon: Task 5 and Task 8.
- RSS with image/media capture: Task 4 and Task 9.
- Top 50 seed feeds: Task 7 and Seed Source Catalog.
- Dockerized runtime: Task 11.
- Firm backend structure: Task 1 through Task 12.
- Future post-agent DB contract: Data Model, repository, and docs tasks.

Placeholder scan:

- This plan contains no placeholder file paths, no unspecified source count, and no incomplete feed list.
- Deferred post generation is intentionally out of scope for this implementation plan; the storage contract supports it through `content_items`, `media_assets`, and source provenance.

Type consistency:

- The same model/table names are used across schema, repository, API, and worker tasks.
- The parser output types are shared by RSS and Telegram public adapters.
- Media candidate fields map directly to `media_assets` and `item_media`.
