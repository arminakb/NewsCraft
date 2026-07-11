# NewsCraft Content Platform Rescue Design

**Date:** 2026-07-11  
**Status:** Approved direction  
**Product mode:** Local, single operator  
**Delivery strategy:** Workflow-first rebuild in place

## 1. Executive Decision

NewsCraft will become a complete local content operations platform rather than an ingestion dashboard. The tested FastAPI, PostgreSQL, ingestion, normalization, deduplication, extraction, media, classification, and scoring foundations remain. The product workflow, scheduling, AI generation, research, Telegram automation, publishing, and frontend information architecture are rebuilt around explicit domain boundaries.

The first live publishing connector is Telegram. Instagram, X, and blog outputs are generated as complete, editable content packages for manual publishing. Their live connectors can be added later without changing the core content model.

Every publishing destination supports two policies:

- `review_required`, which is the default;
- `auto_publish`, which is an explicit per-destination or per-automation opt-in.

A global automation pause always overrides route-level auto-publishing.

## 2. Product Outcomes

The completed platform must let one local operator:

1. Schedule daily collection from RSS, Atom, public Telegram, Google News, GDELT, Hacker News, and manual URLs or text.
2. Search and review a truthful, deduplicated content library with complete provenance.
3. Group related evidence into stories instead of treating every source item as an isolated post.
4. Request additional research when collected evidence is incomplete.
5. Generate grounded content packages for Telegram, Instagram, X, and blogs.
6. Edit, regenerate, version, approve, reject, schedule, export, and publish variants.
7. Configure Telegram-to-Telegram routes that rewrite every new source post with a chosen prompt and either queue it for review or publish it automatically.
8. Preserve and re-upload Telegram photos, videos, documents, and albums by default.
9. Understand every running, failed, waiting, reviewed, scheduled, and published job from the interface.
10. Recover safely from network, model, extraction, media, or Telegram failures without duplicate posts or lost source messages.

## 3. Explicit Non-Goals

- Multi-user accounts, teams, RBAC, billing, and public SaaS deployment are not part of this rescue.
- Instagram, X, and CMS credentials or live publishing connectors are not required for the first complete release.
- AI-generated images and video are not required. The first release uses source media and generates editable media briefs, carousel plans, alt text, and image prompts.
- Kubernetes, Redis, Celery, Kafka, and distributed microservices are unnecessary for the local workload.
- A route never backfills an unbounded Telegram history. New posts are the default; every backfill requires an explicit count or date range.

## 4. Existing Foundation and Replacement Boundary

### Preserve and strengthen

- PostgreSQL and Alembic migrations.
- Source parsers and discovery connectors.
- Raw payload capture and source provenance.
- URL, title, text, date, fingerprint, and media normalization.
- Content deduplication and identities.
- Article extraction and daily bundle logic.
- Media validation and storage.
- Classification, scoring, rewrite readiness, and source health semantics.
- FastAPI, Next.js, TanStack Query, and the existing test harnesses.

### Replace or retire

- The ingestion-monitor-first navigation and dashboard composition.
- Hard-coded health, time, schedule, source, and status values.
- Synchronous network ingestion inside an API request.
- One-shot worker behavior with no scheduler.
- Editorial state stored in overloaded `ContentItem.status` or arbitrary JSON.
- The dead-end approval action that has no generation or publishing continuation.
- The uncalled `DraftService` stub as the draft architecture.
- Runtime mock data and empty initial data that can suppress real queries.

## 5. System Architecture

NewsCraft remains one repository with four runtime processes:

1. **Frontend:** Next.js newsroom interface.
2. **API:** FastAPI validation and orchestration boundary; API requests create jobs instead of performing long network operations.
3. **Worker:** long-running PostgreSQL-backed job executor for ingestion, extraction, research, generation, media, and publishing.
4. **Scheduler:** lightweight process that materializes due schedules as idempotent jobs. It may share worker code but runs as a distinct Compose service.

PostgreSQL is the durable queue and source of truth. Workers claim jobs with row locking, leases, and bounded heartbeats. This keeps the local stack simple while preserving crash recovery and observable job state.

The primary flow is:

```text
Sources -> Collection -> Canonical Content -> Story/Evidence
        -> Optional Research -> Canonical Story Revision
        -> Platform Content Pack -> Review or Auto Policy
        -> Telegram Publish or Manual Export -> Publication History
```

## 6. Domain Boundaries and Data Model

Existing ingestion tables remain the source record. New workflow concepts use explicit tables and typed states.

### Editorial content

- `Story`: editorial unit that groups one or more related content items.
- `StoryEvidenceSnapshot`: immutable title, body, source URL, author, timestamps, and content hash used by a specific research or generation run.
- `StoryRevision`: canonical evidence-backed narrative, facts, disagreements, angles, and citations.
- `StoryEvidenceLink`: connects claims in a story revision to exact evidence snapshots.

### Brand and prompts

- `BrandProfile`: name, output language, tone, editorial rules, attribution rules, default hashtags, and platform preferences.
- `PromptTemplate`: stable purpose key such as `telegram_rewrite` or `daily_news_pack`.
- `PromptTemplateVersion`: immutable system template, user template, output schema version, checksum, and activation state.

### AI and research

- `ResearchRun` and `ResearchAttempt`: requested mode, backend, queries, status, timing, usage, errors, and result revision.
- `ResearchSource`: discovered URL, fetch snapshot, publication metadata, extraction status, relevance, and citation identity.
- `GenerationRun` and `GenerationAttempt`: provider, requested and resolved model, prompt version, input hash, output, token/cost metadata, validation errors, and retry number.

### Output and publishing

- `ContentPack`: one story revision rendered for one brand profile.
- `PlatformVariant`: Telegram, Instagram, X, or blog variant identity.
- `PlatformVariantRevision`: immutable structured content, edit history, evidence mapping, validation results, and approval state.
- `Destination`: Telegram target metadata and a reference to a local secret, never the token itself.
- `PublishJob`, `PublishAttempt`, and `Publication`: approved revision, idempotency key, sanitized payload hash, remote message identifiers, permalink, timestamps, and reconciliation status.

### Automation and jobs

- `AutomationRoute`: source, target, prompt, brand, AI backend, research mode, filters, media policy, publishing policy, schedule, cursor, and enabled state.
- `WorkflowJob`: typed durable work item with priority, schedule, attempts, lease, and error classification.
- `WorkflowEvent`: append-only audit trail for collection, research, generation, edit, approval, scheduling, publishing, retry, pause, and cancellation.

Editorial, variant, and job states are independent. Machine readiness metadata never masquerades as editorial approval.

## 7. Scheduling and Job Engine

The scheduler supports:

- Daily collection schedules in a configured timezone, defaulting to `Asia/Tehran`.
- A configurable daily collection time, defaulting to `06:00` in the configured timezone.
- Per-source fetch intervals and next-due timestamps.
- Telegram route polling intervals.
- Scheduled generation and publishing.
- Manual run-now actions.
- Global and per-route pause controls.

Jobs use deterministic idempotency keys. Examples include a daily collection key derived from schedule and date, a Telegram route key derived from route and source message, and a publish key derived from destination and approved variant revision.

Worker claims use `FOR UPDATE SKIP LOCKED`, lease expiry, and heartbeat timestamps. A crashed worker releases work through lease expiry. A job can be cancelled before execution and can be retried manually after failure.

## 8. Research Enrichment

Every story supports three research modes:

- `off`: use collected evidence only;
- `manual`: run when the operator selects **Research more** or **Deep research**;
- `auto_if_incomplete`: run when a deterministic completeness check finds weak coverage, insufficient sources, missing primary evidence, or unresolved contradictions.

Research produces a new story revision and never overwrites original source content.

### Codex research adapter

The Codex adapter runs `codex exec` in an isolated temporary working directory with:

- ephemeral session mode;
- read-only sandbox;
- ignored user configuration where reproducibility requires it;
- strict JSON Schema output;
- a minimal environment without Telegram credentials;
- hard process, token, and elapsed-time limits;
- captured CLI version, exit code, final output, and sanitized event metadata.

Codex may use its configured web-research capability. The result must contain discovered sources, timestamps, a research brief, verified facts, disagreements, missing information, suggested angles, and claim-level citations.

### OpenRouter research adapter

OpenRouter uses an application-controlled tool loop. The model proposes queries; NewsCraft executes them through a DuckDuckGo search adapter, fetches selected pages through the article extraction boundary, and returns normalized evidence to the model. Follow-up searches are limited by query, page, time, and cost budgets.

The model never invents a successful fetch. Only URLs actually retrieved and snapshotted can become citations.

## 9. Generation and Platform Packages

All providers implement one application-owned interface. OpenRouter is the default normal backend. Codex is an optional local backend. A deterministic fake backend is mandatory for tests and demos. Direct first-party APIs can be added later behind the same interface.

Generation happens in two steps:

1. Produce a canonical story revision grounded in evidence.
2. Render typed platform variants from the canonical revision and brand profile.

### Telegram variant

- Formatted message or caption.
- Source/attribution footer according to route policy.
- Ordered media references and album grouping.
- Optional buttons and canonical link.
- Telegram parse mode and validation result.

### Instagram variant

- Caption, hook, CTA, hashtags, and alt text.
- Carousel slide plan and ordered source-media selection.
- Image briefs or prompts for assets that must be created manually.
- Manual publishing checklist.

### X variant

- Single-post or ordered thread segments.
- Media assignments, link strategy, and alt text.
- Manual publishing checklist.

### Blog variant

- Title, slug, excerpt, body, headings, citations, tags, SEO description, hero-media selection, and canonical-source section.
- Markdown and HTML export.

Every edit creates a new immutable variant revision. Regeneration creates a revision and never destroys human edits. Approval is tied to one exact revision and content hash; editing invalidates prior approval.

## 10. Telegram-to-Telegram Automation

A route connects one Telegram source to one Telegram destination. Multiple routes may consume the same source with different prompts or destinations.

Telegram sources support two explicit access modes. `public_html` reuses the credential-free public channel collector and is marked best-effort. `mtproto_user` uses a locally authenticated Telegram user session for reliable message entities, edits, private channels the user can access, media, and album grouping. MTProto session material is stored as a local secret outside Git and is referenced by name from the database.

Required route settings include:

- source channel and access mode;
- target destination;
- brand profile and prompt template version;
- AI backend and model policy;
- research mode;
- content filters and optional quiet hours;
- media policy: `preserve` by default, `omit`, or `replace_manually`;
- attribution policy: preserve, remove, or custom footer;
- publishing policy: `review_required` by default or `auto_publish`;
- polling schedule, retry policy, and enabled state;
- explicit bounded backfill controls.

For every new source message, NewsCraft captures source identity, text, entities, timestamps, edit state, and grouped media. It downloads and validates source media, creates immutable evidence, applies filters, optionally researches, rewrites, validates, and either queues the revision for review or publishes it.

Albums remain one logical post. A route cursor advances only after the source message has been durably captured and its workflow job recorded. Publication retries reuse the same idempotency key and cannot duplicate a destination post.

Source edits do not silently change a published destination. The first complete release creates a new review revision and leaves the existing destination message unchanged. Automatic remote-message updates are explicitly outside this rescue scope.

## 11. Telegram Publishing

The destination adapter uses a bot that is an administrator of the target channel. It supports text, photos, videos, documents, captions, and media groups. Long outputs are validated and split only through an explicit platform renderer, never by arbitrary substring slicing.

Publishing records the exact approved revision, payload hash, returned message identifiers, publication timestamp, and permalink when available. Ambiguous timeouts enter reconciliation instead of blind retry. Telegram rate limits become retryable jobs scheduled from the returned delay.

Credentials live in environment variables or a local secret file outside Git. Database destinations store secret names such as `TELEGRAM_DESTINATION_NEWS_TOKEN`, not token values. AI and research subprocesses never inherit publishing secrets.

## 12. Product Experience

The selected visual direction is **Newsroom Command Center**.

Primary navigation:

- `Today`: daily command center, urgent work, automation health, research results, review queue, and publishing outcomes.
- `Inbox`: truthful source content, related-story grouping, filtering, search, full evidence, shortlist, reject, and bulk actions.
- `Automations`: Telegram route builder, enable/pause, dry run, policy summary, cursor, history, and failures.
- `Drafts`: content packs, generation state, revisions, and failures.
- `Review & Publish`: evidence and citations beside the editor, platform previews, approval, scheduling, Telegram publish, and manual-export actions.
- `Library`: original content, stories, evidence, research, drafts, exports, and publications.

Secondary navigation:

- Sources
- Templates and brand profiles
- AI providers
- Destinations
- Runs and job queue
- Media
- Diagnostics
- Settings

### Core flows

```text
Inbox -> Inspect -> Shortlist -> Research? -> Generate Pack
      -> Edit Variants -> Approve -> Telegram Publish / Manual Export
```

```text
New Telegram Post -> Route -> Capture Album -> Filter -> Research?
                  -> Rewrite -> Review or Auto -> Publish -> History
```

```text
Paste URL/Text -> Extract -> Research? -> Generate Pack -> Review/Export
```

The UI must provide mobile navigation, Persian and RTL content rendering, keyboard access, honest loading/error/empty states, responsive cards, toasts plus durable mutation outcomes, and no hard-coded operational truth.

## 13. Failure Handling and Safety

Failures are classified as:

- `retryable`: temporary network errors, provider overload, Telegram rate limits, and lease loss;
- `needs_review`: incomplete research, weak evidence, schema-invalid output, unsupported media, or low-confidence generation;
- `permanent`: invalid credentials, inaccessible source, unsupported destination, or operator-disabled configuration.

Retryable jobs use bounded exponential backoff with jitter. Exhausted and permanent failures enter an attention queue with sanitized details, attempt history, and manual controls.

Auto-publishing is allowed only when:

- the route and destination are enabled;
- the global pause is off;
- the selected AI and research requirements succeeded;
- structured output and platform validation passed;
- evidence citations resolve;
- media requirements are satisfied;
- the destination health check is valid.

Failure of any gate changes the job to review instead of silently publishing lower-quality content.

## 14. Local Security Model

- Bind API, frontend, and database host ports to `127.0.0.1` by default.
- Keep API keys, Telegram bot tokens, Codex authentication, and session material outside Git and outside database content fields.
- Pass only the minimum environment to each subprocess.
- Separate generation and publishing worker capabilities even if they run from one codebase.
- Redact authorization headers, tokens, cookies, and secret-like values from logs and attempt metadata.
- Do not give an AI provider shell access, Telegram credentials, database credentials, or arbitrary publishing tools.
- Provide an operator-visible global pause and dry-run mode.

## 15. API and Module Boundaries

Backend modules are organized by product responsibility:

- `app/jobs`: queue, leases, scheduler, retries, and worker registry.
- `app/stories`: grouping, evidence snapshots, revisions, and editorial state.
- `app/research`: completeness checks, search/fetch tools, Codex adapter, OpenRouter tool loop, and citations.
- `app/generation`: provider protocol, prompt rendering, structured schemas, attempts, and content packs.
- `app/automations`: Telegram routes, cursors, filters, and orchestration.
- `app/publishing`: destination protocol, Telegram renderer/client, idempotency, attempts, and reconciliation.
- Existing `app/ingestion`, `app/discovery`, `app/media`, `app/content`, and `app/sources` remain focused on collection and content intelligence.

FastAPI route files are split by resource. No route performs long-running network or AI work inline. Mutation endpoints validate input, persist state, enqueue a job transactionally, and return a job identifier.

Frontend code is organized by product feature rather than a single dashboard component tree. Each screen owns typed API hooks, state views, and focused components. Shared UI primitives remain small and demonstrably used.

## 16. Testing and Verification

Implementation follows test-driven development and must preserve the current passing backend and frontend suites.

Required test layers:

1. Unit tests for job transitions, leases, schedules, route filters, idempotency keys, renderers, schemas, completeness checks, and policy gates.
2. Repository tests against PostgreSQL-compatible behavior for job claiming, retries, cursor updates, revision immutability, and transactional enqueue.
3. Provider contract tests shared by fake, OpenRouter, and Codex adapters.
4. Telegram client contract tests using a fake HTTP transport for text, media, albums, rate limits, ambiguous timeouts, and remote identifiers.
5. API tests proving that long operations return jobs and expose progress/failures.
6. Frontend tests for loading, empty, error, pending, success, failure, review, auto, pause, and mobile/RTL states.
7. End-to-end flows for manual content creation, editorial generation, Telegram route review, Telegram route auto mode, global pause, retry, and duplicate prevention.
8. Optional credentialed smoke tests kept outside the normal deterministic suite.

Completion evidence includes backend tests and Ruff, frontend unit tests and type checking, production build, browser tests at desktop and mobile sizes, Alembic upgrade/downgrade checks, Docker Compose validation, job crash-recovery tests, and a local end-to-end Telegram dry run.

## 17. Delivery Decomposition

The rescue is delivered as independently testable releases rather than one giant merge.

### Release 0: Preserve and stabilize the baseline

- Finish and commit the validated cleanup already present on `refactor-cleanup` without mixing generated companion files.
- Fix the empty-initial-data query regression and remove remaining fabricated operational values.
- Establish repeatable backend, frontend, type, build, browser, and Compose gates.

### Release 1: Platform spine and truthful newsroom shell

- Add explicit story, prompt, job, destination, automation, revision, attempt, and event schemas.
- Add scheduler, long-running worker, job APIs, pause controls, and deterministic fake providers.
- Introduce the Newsroom Command Center shell and job/attention views.

### Release 2: Telegram automation vertical slice

- Configure source and destination channels.
- Capture new source messages and albums with durable cursors.
- Rewrite through OpenRouter, preserve media, review or auto-publish, and record publication history.
- Support dry run, bounded backfill, retry, pause, and duplicate prevention.

### Release 3: Editorial research and generation studio

- Add story grouping, immutable evidence, completeness evaluation, Codex research, DuckDuckGo/OpenRouter research, citations, and manual URL/text creation.
- Add canonical stories, content packs, revisions, full editor, and approval workflow.

### Release 4: Multi-platform manual publishing packages

- Add complete Instagram, X, and blog schemas, previews, validation, Markdown/HTML/JSON export, copy actions, media plans, and manual checklists.
- Add scheduling calendar concepts for reviewed Telegram posts and planned manual posts.

### Release 5: Operational hardening and product completion

- Finish mobile/RTL/accessibility behavior, diagnostics, route history, reconciliation, retention controls, backup/restore documentation, and local smoke tooling.
- Run failure injection, credential redaction, crash recovery, and full end-to-end acceptance suites.

Each release must leave working, testable software and cannot rely on a later release to repair its core contract.

## 18. Acceptance Criteria

NewsCraft is rescued when all of the following are true:

- Daily collection runs automatically and visibly.
- Every collected item is saved with truthful source provenance and can be inspected in full.
- Telegram routes process only new posts by default and support explicit bounded backfill.
- Source media and albums survive Telegram rewriting by default.
- OpenRouter and Codex are interchangeable through validated application-owned contracts.
- Research adds retrievable sources and claim-level citations rather than unverified prose.
- Telegram content can be reviewed or auto-published according to explicit policy.
- Instagram, X, and blog packages are complete enough for a human to publish without rewriting them from scratch.
- Editing invalidates approval and publication always references one exact approved revision.
- Retrying cannot create duplicate destination posts.
- Every job and failure is observable and recoverable from the product UI.
- The default home is the Newsroom Command Center, not an infrastructure dashboard.
- The app remains straightforward to run locally and does not expose credentials or services unnecessarily.
