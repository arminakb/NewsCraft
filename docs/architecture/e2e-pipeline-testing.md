# TestSKILL.md — Logical End-to-End Pipeline Test Skill

> Skill for a coding agent operating inside the NewsCraft repository.
> Goal: drive the **real project path** (Sources → Ingestion → Collection trigger →
> AI Research → AI Generate → Drafts) until a **quality news post** is produced —
> never hand-crafting or faking the post yourself.

---

## Mission

Produce a genuine news post by exercising NewsCraft's own pipeline:

```text
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
3. Commit every codebase change: `git commit` after each fix, with a message in
   the repo's conventional style (`type: imperative summary`, e.g.
   `fix: requeue stale research leases on worker restart`).
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

Create an article collection:

```http
POST /article-collections   {"name": "E2E pipeline collection"}   # 201
```

(Backend: `backend/app/api/article_collections.py`; frontend equivalent lives
under `/feed`.)

- Record its `id`.
- This is the **trigger input**: the workflow's `collection_article_added` node
  will reference exactly this id in `config.collection_id`.

### Step 2 — Source collection with 5 sources

Use **existing sources only** (`GET /sources`; backend `backend/app/api/sources.py`,
models in `backend/app/sources`). Policy, in priority order:

1. If ≥5 sources exist, select **exactly 5** and record their ids.
2. If fewer than 5 exist, call the seed endpoint `POST /sources/seed`
   (`backend/app/ingestion/seed_sources.py`, 12+ built-in AI-news RSS sources)
   and then apply rule 1. Record that seeding was necessary in `progress.md`.
3. If seeding is impossible (endpoint fails / no network to register feeds) or
   fewer than 5 usable sources remain, stop this step and report a **blocker**
   in `progress.md` — do not fabricate source rows directly in the database.

Create one source collection containing exactly those 5 source ids:

```http
POST /source-collections            {"name": "...", ...}   # 201
POST /source-collections/{id}/sources                       # add members
```

(Shapes: `backend/app/api/source_collections.py`, schemas in
`backend/app/source_collections/schemas.py`.) Record the collection `id` —
Step 5 ingests it once.

Note: ingesting these feeds requires outbound internet at ingestion time. If
unreachable, report the blocker; the deterministic fake research/generation path
does not remove that dependency because ingestion fetches real feeds.

### Step 3 — Settings dependencies (provider + prompts)

The workflow nodes may only reference resources that already exist in Settings.
**Priority order — always attempt reuse before creating anything:**

1. `GET /llm-providers`: reuse an existing provider that is usable for execution,
   i.e. `enabled: true` with generation capability ready (fresh passing test).
   Prefer an enabled `openai_compatible` provider; accept a fake-protocol
   operator provider if that is what exists. Record its `id`.
2. `GET /prompt-templates` (+ versions): reuse existing **active** versions —
   one for research (e.g. purpose `news_research_starter`) plus the exact active
   set the generate node needs (`canonical_story` + `<platform>_pack` for every
   platform you configure). Capture `{id, checksum_sha256}` per version.

**Fallback (only when nothing usable exists):**

- Provider: create one through the public API and report the creation as a
  fallback in `progress.md`:

  ```http
  POST /llm-providers
  {"name": "E2E Fake", "protocol": "fake", "default_model": "fake-v1"}
  ```
  Fake protocol forbids `base_url`/api keys and needs no connectivity test;
  the row is listed by `GET /llm-providers` and selectable. For an
  `openai_compatible` provider, remember enablement requires a fresh passing
  test (`POST /{id}/test` then `/{id}/enable`); selection/saving works even when
  the test failed but execution does not.
- Prompts: create missing templates/versions through `POST /prompt-templates`
  (+ versions + activation) and report as fallback. Do not hand-edit seeded
  rows in the database.

Never reference the startup-seeded internal "Deterministic Fake" profile — it is
deliberately hidden from selectors.

### Step 4 — Create the workflow

`POST /automations` with a graph (wire format is snake_case; ≤30 nodes).

Registered node `type` values are the API contract — "AI Research" and
"AI Generate" are UI display names, not type strings (see
`backend/app/automations/definitions/registry.py` and
`GET /automation-node-catalog`). The four nodes required here map to:

| # | requirement | exact `type` (display name) |
|---|-------------|------------------------------|
| 1 | article-collection trigger | `collection_article_added` ("Collection article added") |
| 2 | AI Research | `research` ("AI Research") |
| 3 | AI Generate | `generate_content_pack` ("Generate content package") |
| 4 | save to draft | `save_drafts` ("Save to Drafts") |

Node configs:

| # | type | config keys |
|---|------|-------------|
| 1 | `collection_article_added` | `collection_id` = id from Step 1 |
| 2 | `research` | `provider_profile_id`, `prompt_template_version_id` + `prompt_checksum_sha256`, `mode: "auto_if_incomplete"`, `query_budget: 3`, `page_budget: 10`, `time_budget_seconds: 120` |
| 3 | `generate_content_pack` | `editorial_profile_id` (brand profile id from `GET /brand-profiles`), `provider_profile_id`, `prompt_version_ids` + matching `prompt_checksums`, `platforms: ["telegram"]` |
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

Trigger one-shot ingestion for the source collection from Step 2:

```http
POST /source-collections/{id}/ingest      {"mode": "once"}   # 202 accepted
```

(Handler: `backend/app/api/source_collections.py`; the queued job is
`ingest.collect`, executed by the ingestion worker.)

**Measurable success criterion**: at least **3 content items** from the
collection's sources reach status where they are stored in the article
collection from Step 1 (verify via `GET /article-collections/{id}/articles` or
the content-items list filtered to the collection — count ≥ 3). Each newly saved
membership fires the `collection_article_added` trigger, so ≥3 items ⇒ ≥1
`AutomationRun` visible under `GET /automations/{id}/runs`.

If fewer than 3 items arrive: debug along the real path in this order —
source health (`GET /sources/{id}`), ingest run/job errors
(`docker compose logs -f worker-source-generation`, `WorkflowJob` rows),
normalization (`app/normalization`), collection membership logic, trigger
enqueue (`app/automations/definitions/collection_events.py`). Fix root causes,
not symptoms. If items cannot reach 3 because of an external blocker (feeds
unreachable offline), record the actual count and report the blocker.

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
