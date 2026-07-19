# NewsCraft production-readiness and output-quality audit

**Audit date:** 2026-07-14 through 2026-07-15 (Asia/Tehran)  
**Revision tested:** `7826eba`  
**Verdict:** **Not production-ready**  
**Measured readiness score:** **45/100** (release threshold: 85/100 and no critical blocker)

## 1. Executive verdict

NewsCraft has a thoughtful editorial architecture: durable jobs, immutable evidence and revisions, exact-hash approval, citation-aware research, capability-separated workers, deterministic exports, and explicit human review. Those safety properties worked in the deployed system once execution reached them.

The current revision is not production-ready because the unmodified production workflow cannot complete its own official acceptance path:

1. Telegram route activation, pause, and resume commit their database changes but return HTTP 500.
2. A source/generation worker can crash after a handler successfully commits its output but before the durable job is marked complete. The container then remains stopped because the Compose services have no restart policy.
3. The stock Compose configuration forces outbound requests through a nonexistent proxy when proxy variables are blank, so all realistic RSS ingestion initially failed.
4. Every API access-log attempt raises a formatting exception, making a core operational signal unreliable and inflating logs.
5. The deterministic fake provider proves workflow structure, not editorial quality. Its generated copy was generic, English despite a Persian brand, and—in the blog case—repeated the same sentence eight times.
6. Real RSS and Telegram ingestion is operationally promising, but the relevance/readiness model promoted link-only and very thin items and materially misclassified some promotional content.

The system should not be exposed to unattended production traffic until the critical runtime defects are fixed and the full unmodified acceptance workflow passes repeatedly. Live OpenRouter validation was completed after the user configured the credential locally; the intended model returned HTTP 402, one zero-priced structured model returned invalid output, and another exhausted its retry budget on HTTP 429. No live-provider content pack was produced, and no credential value was printed or exposed during the audit.

## 2. Scope and methodology

This review covered the complete repository rather than only tests:

- 527 supported files and approximately 394,727 words were indexed.
- 504 code files and 23 documentation files were mapped into a 6,731-node, 21,685-edge architecture graph with 267 communities.
- Backend, frontend, migrations, Compose topology, operational scripts, release-acceptance documentation, content scoring, ingestion providers, job leasing, scheduling, publishing, exports, and UI behavior were reviewed.
- Fresh isolated PostgreSQL volumes and production Dockerfiles/Compose services were used.
- Actual public RSS and Telegram pages were fetched over the network.
- The repository's official deterministic release-acceptance workflow was run against the deployed stack.
- Backend tests, linting, frontend type checking, component tests, browser tests, live no-mock browser navigation, responsive behavior, and accessibility were evaluated.
- Output quality was assessed from stored source items, deduplicated content, rankings, generated platform revisions, citations, approvals, and export artifacts.

This audit did **not** publish to a real Telegram destination or any social network. Publishing was intentionally disabled. A destructive backup restore was also not performed. These exclusions do not weaken the not-ready verdict because the workflow failed earlier at core state-transition and worker boundaries.

## 3. Architecture and intended behavior

### 3.1 Runtime architecture

NewsCraft is a local, single-operator newsroom built from:

- A FastAPI backend using async SQLAlchemy, asyncpg, Alembic, and PostgreSQL.
- A Next.js/React operator dashboard.
- A durable PostgreSQL job queue with leases, heartbeats, retry classes, job events, idempotency keys, cancellation, and global pause.
- A source/generation worker with ingestion, source, and generation capabilities.
- A publishing-only worker separated from generation credentials.
- A scheduler for source polling and Telegram automation reconciliation.
- Filesystem-backed media staging and deterministic export packages.

The high-level flow is:

`source catalog -> scheduled/manual ingestion -> normalized source items -> deduplicated content -> research/evidence -> platform-specific generation -> immutable revision -> exact-hash approval -> dry-run/publish or manual export`

### 3.2 Editorial intent

The implementation and operational documentation describe a review-first newsroom:

- Evidence snapshots and revision content are immutable.
- Approvals apply to the exact revision hash; editing creates a new revision and requires reapproval.
- Research citations are retained with generated outputs.
- Telegram can be dry-run and published through a reviewed automation route.
- Instagram, X, and blog packages are prepared for manual publication.
- Operators have queue truth, history, diagnostics, source health, pause/resume, and reconciliation controls.

This intended behavior is appropriate for a high-accountability content system. The primary gap is not the design objective; it is runtime correctness and editorial-quality enforcement at the boundaries.

### 3.3 Dependency and reproducibility model

The backend requires Python 3.14 but declares mostly open-ended lower bounds, for example `fastapi>=0.128`, `sqlalchemy>=2.0`, and `uvicorn[standard]>=0.35`. It has no committed lock/constraints file. The frontend has a lockfile, but many direct dependencies are declared as `latest`. These choices make clean builds vulnerable to unreviewed dependency drift.

## 4. Test environment and configuration

| Area | Configuration actually tested |
|---|---|
| Host | CachyOS Linux, kernel `7.1.2-3-cachyos`, Asia/Tehran |
| Source revision | Git commit `7826eba` |
| Docker | Engine client/server `29.6.1`; Compose `5.1.4` |
| Backend container | Python `3.14.6`; FastAPI `0.139.0`; Pydantic `2.13.4`; SQLAlchemy `2.0.51`; asyncpg `0.31.0`; httpx `0.28.1` |
| Database | PostgreSQL `18.4`; Alembic head `0009_operational_retention` |
| Frontend container | Node `26.4.0`; Next.js lock resolution `16.2.10` |
| Main isolated stack | Compose project `newscraft-audit`, fresh named volumes, real network requests, publishing disabled |
| Acceptance stacks | `newscraft-acceptance-audit` and `newscraft-acceptance-audit2`, fresh isolated PostgreSQL volumes |
| Direct-network diagnostic | Audit-only `/tmp` Compose override cleared `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY`; project files were not changed |
| RSS inputs | OpenAI News, IRNA, Zoomit, Hacker News |
| Telegram inputs | `zarinacc_com`, `pytens`, `cvision`, `llm_huggingface` public web pages |
| LLM modes | Deterministic fake provider for structural acceptance; live OpenRouter with `openai/gpt-5-mini`, `openai/gpt-oss-20b:free`, and `qwen/qwen3-next-80b-a3b-instruct:free` |
| Publishing | Real publishing disabled; Telegram dry-run and manual package/export behavior tested |

The local SOCKS proxy at `127.0.0.1:12334` was initially not listening. Direct access to all four authorized public Telegram pages returned HTTP 200, so credential-free public-page ingestion was validated directly. No secret was read into logs or placed in this report.

## 5. Test scenarios, inputs, and actual outputs

### 5.1 Clean production deployment and stock outbound behavior

**Scenario:** Build and start the production Dockerfiles and Compose services with fresh volumes and blank proxy settings, then ingest four real feeds.

**Input:** OpenAI News, IRNA, Zoomit, and Hacker News source records selected from the seeded source catalog.

**Actual output:** Both stock runs contacted all four sources but fetched zero content. Every request failed DNS resolution for the forced proxy hostname. Run IDs:

- `bebaed69-ef85-4df6-8659-02abd269ae1f`: partial, 0 items.
- `8e264f54-931f-4a29-9acf-40deb8b8e832`: partial, 0 items.

**Diagnostic rerun:** Clearing proxy variables only in an audit override produced successful real ingestion:

- Job: `6e9f349b-eb8b-4b76-9acf-40deb8b8e832`
- Ingest run: `00c97e45-4e02-496e-836b-11f016c2cc2a`
- Checked: 4; fetched: 4; failed: 0
- Parsed items: 1,151; unique content: 1,149; detected duplicates: 2
- Media candidates: 80
- Duration: approximately 50.1 seconds

The production default `${HTTP_PROXY:-http://xray-proxy:10808}` substitutes the nonexistent fallback when the variable is unset **or blank**, which contradicts the documented optional-proxy workflow.

### 5.2 Real RSS content-quality results

| Source | Parsed | Mean score | Ready | Media | Main observed behavior |
|---|---:|---:|---:|---:|---|
| Hacker News | 30 | 21.7 | 0 | 0 | Comment/feed fragments; malformed/truncated titles; correctly blocked by insufficient text in many cases |
| IRNA | 30 | 25.3 | 30 | 30 | Persian/RTL content, but summaries can be thin while still ready |
| OpenAI News | 1,041 | 12.0 | 152 | 0 | Archive flood; mostly feed synopsis rather than full article text |
| Zoomit | 50 | 22.8 | 46 | 50 | Generally usable Persian summaries and media |

Aggregate observations:

- All 1,149 unique content records had `quality_status=needs_review`; this field did not discriminate between strong and weak candidates.
- Freshness: 541 archive, 340 stale, 139 evergreen, 105 fresh, and 24 recent.
- 312 content records contained fewer than 100 characters.
- No stored item lacked both a title and content, but syntactic presence did not imply useful substance.
- Example Hacker News item: title `Show HN: I RL-trained an agent that trains models with RL (for ~$1.3k` and content `Comments` (8 characters). It scored 33 but was blocked for insufficient text.
- Example OpenAI item, `How to manage AI investments in the agentic era`, stored only a 159-character synopsis, scored 45, and was marked ready even though the scoring breakdown identified it as not daily news.

The ingestion pipeline is capable of high-volume real retrieval, but it currently confuses feed availability with editorial completeness. Per-source caps, full-text extraction, freshness windows, and stronger minimum-substance rules are needed.

### 5.3 Real public Telegram ingestion

**Inputs:** 20 recent public posts from each authorized channel:

- `zarinacc_com`
- `pytens`
- `cvision`
- `llm_huggingface`

**Actual output:**

- Job: `bb18ca6e-37fc-440b-bafe-e2807f2d2f7f`
- Ingest run: `e504ce24-6f2a-43fe-99ef-c4e068095d79`
- Checked/fetched/failed: 4/4/0
- Source items: 80
- Unique content: 73
- Media candidates: 34
- Duration: approximately 7.1 seconds
- Source health after run: all four healthy, HTTP 200, zero consecutive failures

The seven cross-channel duplicates were manually inspected. All seven were genuine reposts, giving observed precision of 7/7 for this small duplicate set. Examples included `پارت ۱`, `Krea 2 Turbo`, `روش MiCA...`, and `SenseNova...` reposts shared by CVision and LLM Hugging Face.

Per-channel quality:

| Channel | Items | Mean score | Score range | Ready | RTL | Images | Under 100 chars | Mean chars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CVision | 20 | 64.2 | 39–118 | 19 | 20 | 6 | 1 | 702.7 |
| LLM Hugging Face | 20 | 58.9 | 0–131 | 16 | 15 | 7 | 3 | 619.0 |
| Pytens | 20 | 56.1 | 26–103 | 18 | 19 | 4 | 1 | 707.5 |
| Zarin | 20 | 56.6 | 25–89 | 16 | 13 | 8 | 5 | 650.8 |

Classification across the 80 source items was 44 article, 2 news, 5 promo, 6 research, 15 tutorial, and 8 video. Sixty-nine items were marked ready.

Observed strengths:

- 4/4 sources fetched reliably without credentials.
- Persian text, RTL direction, media, timestamps, source links, and crossposts were retained.
- Empty media-only Zarin posts and the 8-character `@lectour` item were correctly blocked.
- Clear discount advertisements classified as promo were blocked.

Observed quality errors:

- A 64-character CVision GitHub reference was marked ready.
- An 80-character link-only LLM Hugging Face post was marked ready with score 51.
- Weak titles such as `پارت ۱`, `شرکت`, `مدل بنیادی`, and `Prompt` were often ready and sometimes highly ranked.
- A CVision course announcement and the reposted `اطلاعیه دوره Agentic AI` were classified as articles; the latter was the highest-scoring item at 131 despite being promotional.
- A Pytens analytical warning about LinkedIn/AI was classified as promo and blocked, a likely false positive.
- A Zarin technical announcement about serverless Telegram bots was classified as promo and blocked, also a likely false positive.
- The LLM Hugging Face source was intentionally configured with an English language hint to test resilience. All 20 records were labeled `language_code=en`, while 15 had RTL direction and visibly Persian content. The system trusts the hint rather than reconciling it with detected script.
- Every item still had `quality_status=needs_review`, including high- and low-scoring records.

### 5.4 Official deterministic acceptance workflow

**Scenario:** Run the repository's release-acceptance smoke workflow against a clean, deployed stack.

**Stock result:** Failed during configure after 391 ms. `POST /telegram/automations/{route_id}/activate` committed route activation and enqueued initialization, then returned HTTP 500.

**Audit-only continuation:** A temporary script reconstructed only the missing 202 response from the already-committed state through public read APIs. This did not modify application code. The downstream workflow then passed:

- Health and configuration checks
- Manual story intake
- Immutable source evidence
- Cited research
- Four-platform generation
- Edit, hash invalidation, and exact reapproval
- Telegram dry-run with album preservation and idempotency

Key identifiers:

- Route: `371b1756-7174-411f-9fb5-312e94137909`
- Story: `cb748ecb-4468-4686-b828-0a4cdd4fdbda`
- Content pack: `b1cf16ed-5c82-4199-9a1a-59d12216e552`
- Export job: `fef7ae2a-6849-480d-8293-c5904511bcab`

The continuation did **not** produce a valid full pass. After a Telegram route handler generated and committed a new revision and emitted `telegram.revision.review_required`, the source/generation worker crashed before marking job `6bb5b2db-7e5b-4431-822b-8f4762a31f6f` complete. The export then timed out after 300 seconds because the only capable worker was stopped.

After manually restarting the worker and cancelling the recovered, already-materialized route job, operational recovery succeeded:

- Export status: succeeded
- Export manifest checksums: verified
- Downloaded export bytes: verified
- Manual publication plan: ready
- Manual checklist: completed
- History records: 59, including story, route, and pause events
- Secret canary: absent from history/diagnostic output
- Scheduler, source/generation worker, and publishing worker: healthy after recovery
- Queue global pause/backfill behavior: correct after resume

Pause and resume nevertheless returned HTTP 500 even though their database side effects committed.

### 5.5 Generated output quality

The fake provider is intentionally deterministic, so these examples measure the system's structural controls and its minimum quality safeguards—not the quality of a real model.

Actual platform outputs included:

- Telegram: `Deterministic Telegram rewrite` followed by the smoke identifier.
- Instagram: generic English text beginning `The verified acceptance story is confirmed...`.
- X: the same generic English framing.
- Blog: `The immutable source snapshot confirms the deterministic acceptance story.` repeated eight times.

Assessment:

- **Accuracy/evidence:** Structural evidence links and hashes were present; no unsupported factual expansion was observed because the text was almost entirely templated.
- **Relevance:** Low. The output did not meaningfully transform the story for its platforms.
- **Completeness:** Low. No useful narrative, context, audience adaptation, or platform-specific substance was generated.
- **Consistency:** Structurally strong but linguistically wrong: English output was produced for a Persian brand/profile.
- **Clarity:** Grammatically readable but repetitive and content-poor.
- **Reliability:** Exact-hash approval and export reproducibility worked after recovery; uninterrupted generation-to-export did not.
- **Objective alignment:** The review controls align with the project objective; the generated editorial value does not meet it.

Real-model quality cannot be inferred from fake-provider output. The subsequent live OpenRouter validation produced no usable draft, so production editorial quality remains unproven and the quality score is capped accordingly.

### 5.6 Backend verification

- Full suite initial result: 1,596 passed, 2 failed, 1 warning in 249.62 seconds.
- Both failures were test-environment assumptions rather than application assertions: the backend image lacked `.venv/bin/alembic`, and it lacked a Docker CLI.
- The Compose configuration test passed in a disposable container with the required Docker CLI access.
- The migration test passed against a dedicated, migrated temporary PostgreSQL database with the expected workspace shim.
- Effective result: all 1,598 backend assertions passed when their documented/implicit environment preconditions were supplied.
- Ruff passed for application and test code.
- One deprecation warning indicates Starlette `TestClient` behavior that will require the httpx 2 migration.

This strong unit/integration count did not detect the deployed `MissingGreenlet` failures or Uvicorn access-log failure. The gap is specifically at real async-session commit/serialization boundaries and formatter integration.

### 5.7 Frontend and browser verification

- TypeScript type check: passed.
- Vitest: 368/370 passed.
- One jobs-page failure passed alone and appears concurrency/resource-sensitive.
- The Story Inbox test timed out consistently at its explicit 10-second limit while rendering and bulk-selecting 201 complex rows; observed duration was approximately 10.6–11.7 seconds. The page lacks pagination or virtualization at that test size.
- Multiple variant-editor tests emitted React `act(...)` warnings.
- Playwright mocked suite: 23/33 passed. Ten failures were dominated by mock/contract drift, including an unhandled live `GET /telegram/reconciliation`, stale diagnostics labels, and stale desktop control assumptions.
- A separate browser crawl against the actual deployed Next.js frontend and API loaded the critical routes without page exceptions or horizontal overflow at desktop and mobile widths.
- Axe found no serious/critical issues on most pages, but Diagnostics had a serious color-contrast violation at desktop and mobile widths.
- The real `/automations` and `/content` routes returned 200. A fixture-specific media URL with an unknown scheme caused `ERR_UNKNOWN_URL_SCHEME` in the content UI, showing weak defensive URL handling.
- First-load timing for Today was approximately 13.1 seconds in the audit environment; most subsequent routes took 2.8–5.8 seconds including browser/navigation settling.

### 5.8 Dependency audit

`npm audit` reported two moderate vulnerabilities and no high or critical vulnerabilities. The material advisory was PostCSS XSS (`GHSA-qx2v-qp2m-jg93`, CVSS 6.1): the lock resolved PostCSS 8.4.31, while the fixed range begins at 8.5.10. It is pulled through the current Next resolution. The automated proposed fix was not applied because it suggested an implausible major/downgrade path and requires compatibility validation.

The frontend dependency tree contained 528 packages: 346 production, 147 development, 80 optional, and 7 peer packages.

### 5.9 Live OpenRouter generation validation

**Scenario:** Create one internal story from the real public Telegram post `https://t.me/zarinacc_com/1003`, then request Persian drafts for Telegram, Instagram, X, and blog. Research, approval, scheduling, and publishing were disabled. The default Persian brand and active production prompt versions were used.

**Input and internal evidence:**

- Manual intake job: `9f2fa511-d602-4fc7-a6f1-58988a41997a`
- Story: `e278f4ff-5bb2-4a86-9ee3-0418bd5635ef`
- Subject: Google CodeWiki described as an interactive documentation aid for open-source repositories
- Source: the already-ingested Zarinacc public Telegram post, preserved as immutable story evidence

**Attempt 1 — intended production profile:**

- Model: `openai/gpt-5-mini`
- Job: `c4025d65-0669-4474-a998-b5bed18d36db`
- Result: permanent failure, `openrouter_http_402`
- Provider latency: 1.09 seconds from job start to finish
- Interpretation: the credential was loaded and the provider was reached, but the account lacked the credit required by the configured model
- Output: none; no content pack or platform revision was created

**Attempt 2 — zero-priced structured-output fallback:**

- Model: `openai/gpt-oss-20b:free`
- Job: `0b657627-1b1c-4571-90f1-6a5ac38f9d6c`
- Provider HTTP result: 200
- Result: `needs_review`, `openrouter_output_invalid`
- Latency: 22.55 seconds
- Output: rejected before canonical revision persistence; no content pack created
- Diagnostic limitation: the adapter maps JSON parsing, response schema, usage, finish reason, model metadata, redaction revalidation, and Pydantic errors to the same code and discards the invalid response, so the precise malformed field cannot be recovered

**Attempt 3 — final multilingual zero-priced fallback:**

- Model: `qwen/qwen3-next-80b-a3b-instruct:free`
- Job: `c1edd836-126e-424f-8873-f7cccba74370`
- Results: HTTP 429 on attempts 1, 2, and 3
- Retry intervals: approximately 30 seconds, as scheduled by the durable queue
- Final state: failed after exhausting the three-attempt budget in approximately 64.9 seconds wall time
- Output: none; no content pack created

The provider path therefore failed the production objective under every available account condition. The application correctly kept invalid/failed output out of the editorial database, sanitized provider errors, classified 402 as permanent, classified 429 as retryable, and exercised its retry budget. However, it produced no content that could be evaluated for factual accuracy, citation fidelity, language adherence, clarity, or platform fit.

A further idempotency defect was discovered during the fallback: changing the model on an existing provider profile and resubmitting returned the previous failed job as `deduplicated=true`. `EditorialService.request_content_pack()` hashes the provider profile ID in the request payload but not the profile's resolved model or configuration version. A new profile ID was required to perform a genuine retry with the changed model.

## 6. Issues and root causes

### Critical

#### C1. State-changing Telegram route endpoints return HTTP 500

**Evidence:** Activation, pause, and resume all committed their changes but failed response serialization. Activation also enqueued its durable job before returning 500.

**Root cause:** After `await session.commit()`, SQLAlchemy expires the route attributes. Pydantic response construction accesses server-updated `updated_at`, which attempts asynchronous lazy loading outside the expected greenlet and raises `MissingGreenlet`. Activation returns the expired model at `backend/app/api/telegram_automations.py:312`; pause and resume return it at lines 320 and 328. Dry-run and backfill have the same post-commit return pattern and should be audited even where a failure was not observed.

**Impact:** Clients see failure despite committed side effects, encouraging unsafe retries and making API state ambiguous.

#### C2. Worker crashes after successful handler commit

**Evidence:** A Telegram handler committed a generated revision and review event, after which the worker crashed before `finish_job`; the lease later recovered the job to queued state and the export starved.

**Root cause:** `backend/app/jobs/worker.py:340` and subsequent logging/failure paths access `job.id`, `job.job_type`, and `job.attempt_count` after handler-controlled transaction activity has expired the ORM instance. Access triggers `MissingGreenlet` outside an awaited ORM operation.

**Impact:** At-least-once execution becomes externally visible, work may materialize while the job remains incomplete, and the only source/generation worker exits.

#### C3. No restart policy for critical services

**Evidence:** After C2, the source/generation container stayed exited and no worker could process export/generation jobs.

**Root cause:** The Compose services do not define a restart policy or external supervisor behavior.

**Impact:** A single unhandled process exception turns a recoverable durable-queue condition into indefinite production outage.

### High

#### H1. Blank optional proxy settings force a nonexistent proxy

**Root cause:** Compose lines 46–48 and equivalent worker/scheduler blocks use `${VAR:-http://xray-proxy:10808}`. Compose treats both unset and empty values as conditions for the hardcoded fallback.

**Impact:** Out-of-box external ingestion fails for operators who follow the documentation and leave optional proxy variables blank.

#### H2. Access logging fails on every request

**Root cause:** `_RedactingFilter` renders and mutates each `LogRecord`, then replaces `record.args` with an empty tuple in `backend/app/core/logging.py:43-44`. Uvicorn's access formatter expects its five structured access arguments and raises `ValueError: not enough values to unpack`.

**Impact:** Access logs are unusable, error volume is inflated, and operational request diagnostics are obscured.

#### H3. Output-quality gates allow thin/link-only content

**Evidence:** 312/1,149 RSS records were under 100 characters; four representative Telegram items of 64–99 characters, including an 80-character link-only post, were marked ready.

**Root cause:** Positive source, freshness, keyword, engagement, media, and type bonuses can exceed readiness thresholds without a hard minimum of meaningful non-URL text. Title quality checks also miss short generic titles.

**Impact:** Operators receive high-ranked candidates with insufficient context for trustworthy editorial production.

#### H4. Promotion and source-quality scoring is brittle

**Root cause:** Source tier is hardcoded by matching name/URL substrings in `backend/app/content/scoring.py:139-156`; promotional classification relies on keyword heuristics. A tier-A bonus can amplify a misclassified promotional post.

**Impact:** Promotional material can become the top candidate, while legitimate analytical or product-engineering material can be suppressed.

#### H5. Live OpenRouter generation produces no usable output

**Evidence:** The intended model failed with HTTP 402; a zero-priced model returned HTTP 200 but failed structured validation; a second zero-priced model received HTTP 429 on all three scheduled attempts.

**Root cause:** The intended account/model combination lacks provider credit. Free-tier alternatives are not a production substitute: one violated the application output contract and the other was unavailable under its rate limit.

**Impact:** Language adherence, factual support, hallucination rate, citation faithfulness, tone, and real platform adaptation cannot be scored because no live draft reached persistence.

#### H6. Invalid provider output is not diagnosable

**Root cause:** `backend/app/generation/providers/openrouter.py:203-216` catches parsing, JSON Schema, Pydantic, usage, finish-reason, and response-shape failures together, emits only `openrouter_output_invalid`, and retains no safe field-level failure descriptor.

**Impact:** Operators cannot distinguish a model contract failure from usage-metadata drift or an adapter bug, making provider selection and incident resolution unnecessarily speculative.

### Medium

#### M1. Official smoke test is not safely rerunnable after early failure

**Root cause:** The workflow uses a hard-coded Telegram channel reference (`example_channel`). A failed run leaves committed records, so a rerun on the same database receives HTTP 409 despite a unique smoke run ID.

#### M2. Mocked browser acceptance suite has contract drift

**Root cause:** Fixtures and route intercepts were not updated alongside reconciliation and diagnostics UI/API changes.

**Impact:** Ten of 33 browser checks fail, reducing the suite's value as a release gate even though the live UI is healthier than the mocked result suggests.

#### M3. Story Inbox large-list performance is outside its test budget

**Root cause:** More than 200 complex rows and bulk selection rerender without pagination/virtualization.

#### M4. Language metadata trusts hints over content

**Root cause:** The source hint is persisted as language code while direction is derived independently from script, allowing `language_code=en` with RTL Persian text.

#### M5. Dependency builds are not fully reproducible

**Root cause:** Open-ended backend lower bounds and frontend `latest` declarations permit clean installations to change without a source diff. The lock also currently includes a moderate PostCSS advisory.

#### M6. Accessibility and media URL hardening gaps

**Evidence:** Serious color contrast on Diagnostics; unknown-scheme media can reach the browser and generate URL errors.

#### M7. Content-pack idempotency ignores provider model changes

**Root cause:** `backend/app/generation/editorial_service.py:241-257` hashes the generation request containing `generation_provider_profile_id`, but does not snapshot/hash the profile's resolved model or configuration version. The worker resolves the mutable profile later.

**Impact:** Changing the model on a provider profile and resubmitting can return a stale failed job instead of executing the newly selected model. It also weakens reproducibility between enqueue and execution.

## 7. Measurable quality assessment

The release threshold used here is 85/100 with no critical issue, no uninterrupted E2E failure, and a validated production generation provider. Scores are based on observed pass rates and failure severity, not test-count alone.

| Dimension | Weight | Score | Measurement and rationale |
|---|---:|---:|---|
| Real ingestion reliability | 15 | 9 | Direct override: RSS 4/4 and Telegram 4/4 succeeded; stock production configuration: RSS 0/4 twice because of forced proxy |
| Semantic and editorial output quality | 25 | 7 | Good Telegram retention/dedup; 312/1,149 thin RSS items; 69/80 Telegram ready includes thin/link-only items; fake copy is not publishable; three live-provider paths produced no usable output |
| Evidence and editorial safety | 15 | 14 | Immutable evidence, cited research, exact-hash reapproval, dry-run idempotency, secret redaction, and checksum verification passed |
| Uninterrupted end-to-end workflow | 20 | 8 | Official flow failed at activation; audit continuation later lost its worker and timed out; recovery only succeeded after manual intervention |
| Operational reliability/observability | 15 | 3 | State-changing 500s, worker crash, no restart policy, and broken access logging |
| Operator UI and accessibility | 5 | 3 | Live critical routes usable/no overflow; Diagnostics contrast, large-list performance, and stale browser suite remain |
| Security and reproducibility | 5 | 1 | No high/critical npm advisory, but moderate XSS advisory plus unbounded dependency declarations and no backend lock |
| **Total** | **100** | **45** | **Below 85 release threshold; critical blockers present** |

Quality-specific verdicts:

| Criterion | Verdict | Evidence |
|---|---|---|
| Accuracy | Unproven for real generated copy | Evidence controls work; live provider attempts produced no persisted copy to evaluate |
| Relevance | Weak | Archive flood and material promo-classification errors; generic fake outputs |
| Completeness | Weak | 312 short RSS records; feed synopsis frequently treated as sufficient; generated copy lacks substance |
| Consistency | Weak-to-moderate | Strong structural hashes/exports; inconsistent language metadata and English output for Persian profile |
| Clarity | Weak | Weak generated titles and eightfold repeated blog sentence |
| Reliability | Failing | Unmodified E2E cannot finish; state changes return 500; worker exits |
| Objective alignment | Mixed | Excellent review/evidence architecture; current ranking and generated output do not yet deliver production newsroom quality |

## 8. Recommendations and release gates

### Priority 0: runtime correctness

1. Refresh or explicitly serialize Telegram route models after commit. Add deployed async integration tests for activate, pause, resume, dry-run, and backfill that assert both the HTTP response and committed state.
2. Snapshot immutable job identifiers/type/attempt values before invoking handlers; never depend on an ORM instance after handler-controlled transaction boundaries. Add a regression test where the handler commits and expires session objects.
3. Add `restart: unless-stopped` (or a production orchestrator equivalent), liveness monitoring, and an alert for zero healthy workers with queued capable jobs.
4. Make proxy configuration truly optional. Remove the nonexistent hard default; validate configured proxy reachability at startup and expose it in diagnostics without secrets.
5. Preserve Uvicorn access-record structure during redaction. Redact a copied/safe view or use a formatter that understands access fields. Add a test using Uvicorn's real AccessFormatter and five-element arguments.

**Exit gate:** Ten consecutive clean official smoke runs on fresh databases and three consecutive reruns on the same database, with zero HTTP 500, zero worker exit, zero lease recovery caused by process failure, and all exports completed within the documented SLO.

### Priority 1: editorial quality

1. Introduce per-source ingestion policies: maximum items/run, maximum age, full-text extraction strategy, allowed content types, and archive behavior.
2. Require a measurable minimum of meaningful non-URL text for readiness, with explicit exceptions for reviewed media-first formats. A starting threshold of 120–200 non-URL characters should be calibrated on a labeled dataset.
3. Add title-quality rules for fragments, generic Telegram identifiers, incomplete punctuation, link-only titles, and generic one-word headings.
4. Replace hardcoded source-name tiers with operator-configurable source reputation/versioned policy. Store why a tier was assigned.
5. Train/calibrate promotion and low-signal classification on labeled Persian and English examples. Prevent source bonuses from overriding a strong promo/low-substance blocker without human review.
6. Reconcile language hints with detected script and flag conflicts instead of silently persisting contradictory metadata.
7. Make `quality_status` meaningful with calibrated states and reasons rather than assigning `needs_review` universally.

**Exit gate:** On a minimum 200-item stratified real-source corpus, dedup precision >=98%, ready precision >=90%, promo precision/recall >=90%, language/script agreement >=98%, and fewer than 2% of ready text items below the approved substance threshold.

### Priority 1: real generation validation

Run at least 30 representative stories across Persian/English, RSS/Telegram, news/tutorial/research/promo-borderline, short/long, and conflicting-source cases using the real configured provider. Review blind against a rubric:

- Citation coverage: 100% of factual claims traceable to evidence.
- Unsupported material claims: 0 critical; <=2% minor claim rate.
- Language/profile adherence: >=95%.
- Required platform fields/schema: 100%.
- Non-repetition: >=95% of outputs without repeated sentence/paragraph defects.
- Human ratings for accuracy, relevance, completeness, clarity, and platform fit: mean >=4.2/5, no dimension below 4.0.
- Repeated-run structural reliability: >=99% valid schema and completed job rate.

Real Telegram publishing should be tested only after the user supplies a controlled destination credential locally and explicitly authorizes the external action.

### Priority 2: release engineering and UI

1. Make smoke data unique per run and add cleanup/finalization so early failure does not poison reruns.
2. Update mocked Playwright intercepts and assertions to current API/UI contracts, then retain a smaller no-mock deployed acceptance suite as the primary truth.
3. Paginate or virtualize Story Inbox; measure interaction latency at 200, 1,000, and 10,000 rows. Target p95 bulk-selection response under 500 ms.
4. Fix Diagnostics color contrast to WCAG AA and reject unsupported media URL schemes before rendering.
5. Commit a backend lock/constraints strategy; replace frontend `latest` with reviewed compatible ranges; update PostCSS through a compatible Next release/override and rerun all UI/security tests.
6. Add production-like formatter/session/container-exit tests because the current 1,598 backend assertions missed all critical deployed failures.

## 9. Audit findings versus implemented fixes

**Audit findings:** Everything in sections 5–8 was observed or inferred from the tested revision and runtime evidence.

**Implemented application fixes:** **None.** No application source code, committed Compose file, dependency declaration, or database migration was changed. Audit-only Compose overrides and continuation/recovery scripts were created under `/tmp`; they are explicitly excluded from the production-readiness result.

**Authorized local configuration adjustment:** After the user granted permission, the existing bare secret value in the ignored root `.env` was mechanically prefixed with `OPENROUTER_API_KEY=` so Compose could load it. The value was never printed. Two temporary provider profiles and one audit story were created only in the isolated audit database. These adjustments enabled testing; they do not fix any product finding.

## 10. Evidence index

- Architecture report: `graphify-out/GRAPH_REPORT.md`
- Interactive architecture graph: `graphify-out/graph.html`
- Machine-readable graph: `graphify-out/graph.json`
- Stock smoke artifact already present in the workspace: `validation/production-readiness-2026-07-14/smoke-results/smoke-20260714T203527258821Z-55fbb26b.json`
- Audit-only raw acceptance and recovery evidence: `/tmp/newscraft-acceptance-output/`
- Live-browser screenshots: `/tmp/newscraft-desktop-today.png`, `/tmp/newscraft-desktop-diagnostics.png`

Raw `/tmp` artifacts are diagnostic evidence and may not survive host cleanup. The stable facts, identifiers, measurements, and relevant failure paths are preserved in this report.

## 11. Final decision

**Do not release this revision to production.**

NewsCraft's safety-oriented architecture is a strong foundation, and real ingestion plus immutable editorial controls demonstrated meaningful capability. However, production readiness requires an uninterrupted workflow, truthful API responses, surviving workers, usable access logs, deterministic deployment configuration, and empirically acceptable real-model output. The tested revision currently fails those requirements; live OpenRouter testing produced no usable content pack. Reassess only after the Priority 0 fixes pass the stated repeated-run gate, a funded production model completes repeatedly, and the real-provider quality corpus clears its rubric.
