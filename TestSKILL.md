# TestSKILL.md — Logical End-to-End Pipeline Test Skill

> Skill for a coding agent operating inside the NewsCraft repository.
> Goal: drive the **real project path** (Sources → Ingestion → Collection trigger →
> AI Research → AI Generate → Drafts) until a **quality news post** is produced —
> never hand-crafting or faking the post yourself.

---

## Mission

Produce a genuine news post by exercising NewsCraft's own pipeline:

```
Source Collection ──ingest──▶ Content Items ──▶ Article Collection
        │                                              │ (collection_article_added trigger)
        ▼                                              ▼
                                              Workflow: research → generate → save_drafts
                                                             │
                                                             ▼
                                            PlatformVariantRevision ("the news post")
```

**Hard rules**

1. The post must come from the workflow runtime (`AutomationRun` → jobs → handlers).
   If you are about to write article text yourself, you have left the mission.
2. Fix logical bugs and dependency issues you encounter — but fix them *well*:
   respect the macro architecture (durable state in PostgreSQL, backend-authoritative
   validation, worker isolation, no secrets in snapshots/logs/frontend).
   No bypass hacks (e.g., inserting revisions directly into the DB, disabling
   validation, hardcoding outputs).
3. Commit every codebase change: `git commit` after each fix, with a clear message.
4. Report progress continuously in `progress.md` (repo root): what you did, what
   failed, what you changed, what is blocked.
5. Report blockers explicitly (no internet, missing credentials, flaky infra)
   instead of working around them silently. If live LLM access is unavailable,
   switch the whole chain to the built-in deterministic fake provider and say so
   in `progress.md`.

---

## Phase 1 — Collection-triggered news production

### Step 0 — Environment up

```bash
docker compose up --build -d          # api :8000, frontend :3000, postgres :5432
curl http://127.0.0.1:8000/health/ready   # must report schema_current + database_connected
```

Notes:
- If a `docker-compose.local.yml` override exists, always pass the same `-f` set
  that created the running containers; mixing file sets detaches postgres onto a
  different compose network and breaks DNS (`newscraft-postgres` unresolvable).
- All REST endpoints and schemas are in `contracts/openapi.json` (regenerate with
  `cd backend && uv run python scripts/export_openapi.py --output ../contracts/openapi.json`
  if you change schemas). Verify any route you are unsure about there before calling it.

### Step 1 — Article collection

Create an article collection via the article-collections API
(`backend/app/api/article_collections.py`; frontend equivalent lives under `/feed`).

- Record its `id`.
- This is the **trigger input**: the workflow's `collection_article_added` node
  will reference exactly this id in `config.collection_id`.

### Step 2 — Source collection with 5 sources

Use the **existing sources** (Settings → Sources / `backend/app/sources`,
`backend/app/source_collections`). Do not invent new sources unless fewer than 5
exist — if you must add some, prefer offline-safe ones (local/RSS fixtures) and
report it.

- Create one source collection containing exactly 5 existing source ids
  (`backend/app/source_collections/`, see also `tests/postgres/test_source_collections_*.py`
  for the API shape).
- Record the collection `id` — Step 5 runs one-shot ingestion on it.

### Step 3 — Settings dependencies (provider + prompts)

The workflow nodes may only reference resources that already exist in Settings.

**LLM provider**

- Prefer the deterministic route when internet is not guaranteed: create an
  operator fake provider through the public API:
  ```http
  POST /llm-providers
  {"name": "E2E Fake", "protocol": "fake", "default_model": "fake-v1"}
  ```
  (fake protocol forbids `base_url`/api key; the row is listed by `GET /llm-providers`
  and selectable by nodes. The startup-seeded internal "Deterministic Fake" profile
  is deliberately hidden from selectors — do not try to reference it.)
- If real internet + API key are available, an `openai_compatible` provider works
  too, but remember: **enablement requires a fresh passing connectivity test**
  (`POST /llm-providers/{id}/test` then `/enable`). Selection/saving works even
  when the test fails; execution does not. Report which path you took.

**Prompts**

- Research node: pick an **active** prompt version from `GET /prompt-templates`
  (+ versions endpoint); capture `{id, checksum_sha256}` of the active version.
  `News Article Research — Structured Evidence` (purpose `news_research_starter`)
  is seeded for exactly this.
- Generate node requires the **exact active set** for the chosen platforms:
  `{canonical_story} ∪ {<platform>_pack …}` — e.g. for `"platforms": ["telegram"]`
  pin active versions of `canonical_story` and `telegram_pack` with their
  checksums. Runtime rejects anything else (409 `automation_resource_unavailable`).

### Step 4 — Create the workflow

`POST /automations` with a graph (wire format is snake_case; ≤30 nodes):

Node order and configs:

| # | type | config keys |
|---|------|-------------|
| 1 | `collection_article_added` | `collection_id` = id from Step 1 |
| 2 | `research` | `provider_profile_id`, `prompt_template_version_id` + `prompt_checksum_sha256`, `mode: "auto_if_incomplete"`, `query_budget: 3`, `page_budget: 10`, `time_budget_seconds: 120` |
| 3 | `generate_content_pack` | `editorial_profile_id` (brand from settings), `provider_profile_id`, `prompt_version_ids` + matching `prompt_checksums`, `platforms: ["telegram"]` |
| 4 | `save_drafts` | `{}` |

Wiring rules (validated server-side):
- ports: trigger `story` → research `story`; research `story` → generate `story`;
  generate `drafts` → save_drafts `drafts`.
- `output_node_ids`: `["<save_drafts node id>"]`.
- Save creates draft version 1 (`POST /automations/{id}/versions` for edits,
  `Idempotency-Key` header required). Then activate the workflow
  (lifecycle action) so triggers can fire; activation re-validates resources and
  will refuse if the provider/prompts aren't ready — fix upstream in Settings,
  don't weaken validation.

### Step 5 — Ingest once

Trigger one-shot ingestion for the source collection from Step 2 (see
`backend/app/source_collections/` run-once entry point and its API route;
frontend equivalent: Source Collections "run" action).

Success means: a few content items are ingested, normalized, and inserted into
the article collection from Step 1, which enqueues the
`collection.article_added` trigger → an `AutomationRun` appears
(`GET /automations/{id}/runs`).

If items don't reach the collection: debug along the real path —
source health, normalization (`app/normalization`), collection membership logic
(`app/content`), trigger enqueue (`app/automations/definitions/collection_events.py`).
Fix root causes, not symptoms.

### Step 6 — Follow the run to the news post

Poll `GET /automations/{id}/runs/{run_id}` and job state until terminal:

- Worker containers execute `research_story` → `content_pack.generate(_telegram)`.
  Watch `docker compose logs -f worker-source-generation` for handler errors.
- On success: find the `PlatformVariantRevision` rows
  (`approval_state == "pending_review"`). **That revision's `content` JSON is the
  news post.**
- Confirm the review boundary held: no `PublishJob`/`Publication` rows were
  created (dry-run/review defaults). Publishing is out of scope for Phase 1.

### Step 7 — Judge quality (acceptance criteria)

The post passes only if **all** hold:

1. Provenance: produced by an `AutomationRun` whose node runs link to real
   `ResearchRun`/`GenerationRun` rows (check `AutomationNodeRun.research_run_id` /
   `generation_run_id`).
2. Groundedness: claims trace to captured evidence via `evidence_map` /
   citations; no invented sources (verify citation URLs exist among ingested
   evidence snapshots).
3. Coherence: headline + body read as publishable news (language matches brand
   profile, tone/direction respected, no template residue like `{placeholder}`).
4. Contract: content satisfies the platform payload validation used at approval
   time (`validate_platform_payload` path); `validation_results` show no errors.
5. Honesty: speculation/failure states from research (missing information,
   disagreements) are reflected, not papered over.

If quality fails, iterate on the **configuration inputs** (prompt wording via a
new immutable prompt version + activation, budget sizes, brand profile) — never
by editing the generated content.

### Bug-fixing policy

- Reproduce → locate the owning layer (API schema / service / handler /
  validation / migration) → minimal principled fix → add/extend a test next to
  the existing suite (`backend/tests/…`, mirroring nearby patterns) → run the
  affected suites:
  ```bash
  cd backend && TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
    uv run python -m pytest <touched areas> -q
  cd backend && uv run ruff check . && uv run mypy app
  cd frontend && npm run typecheck && npm run test
  ```
  (Start the disposable test DB with the repo's `scripts/test_postgres.sh`.)
- Alembic migration required for any DB change. Backend stays authoritative;
  never duplicate validation client-side; never log/expose secrets.
- One commit per logical fix; update `progress.md` in the same commit.

### Blockers to report immediately

- No internet (live providers/search unreachable) → state it, fall back to the
  fake provider path, continue.
- Missing Telegram credentials → irrelevant for Phase 1 (publishing skipped);
  do not configure publishing just to "finish".
- Flaky infra (compose networks, test DB down) → restart cleanly per Step 0
  notes; record occurrences in `progress.md`.

### progress.md format

Append one block per work item:

```
## <UTC timestamp> — <step>
- Did: …
- Result: pass | fail | blocked
- Changed: <files> (<commit sha>)
- Evidence: <ids, endpoints, log lines, test names>
- Next: …
```

---

## Later phases (placeholders)

- **Phase 2** — human review approve → publishing path with Telegram destination.
- **Phase 3** — multi-platform packs, scheduled triggers, retention.
Define each phase in this file before executing it, same rules apply.
