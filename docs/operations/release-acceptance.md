# Release 5 Acceptance Evidence

Date: 2026-07-14

Branch: `refactor-cleanup`

Acceptance mode: deterministic fake provider, Telegram dry run, no live credentials

## Result

The code, database, frontend, browser, migration, and static Compose gates pass locally. The
container runtime gate and live HTTP smoke remain environmentally blocked because this host has
no Docker socket at `/var/run/docker.sock`. They are not reported as passed.

The PostgreSQL gate starts from a fresh schema migrated to Alembic head. This is required by the
destructive dispatch-migration regression, which must have a truthful `alembic_version` before it
can downgrade to the Release 2 schema. Creating tables with SQLAlchemy metadata alone is not an
equivalent migration-test setup.

## Automated gates

| Gate | Result |
| --- | --- |
| Fresh Alembic `upgrade head` | Passed; head is `0009_operational_retention` |
| Alembic downgrade to `0008_manual_publication_plans` and re-upgrade | Passed |
| Full backend with `TEST_DATABASE_URL` on PostgreSQL 18.4 | Passed: 1,598 tests |
| Ruff | Passed |
| Smoke-driver contract | Passed: 2 tests |
| Frontend unit/component suite | Passed: 47 files, 370 tests |
| Frontend typecheck | Passed |
| Frontend production build | Passed; 17 static pages generated |
| Chromium browser acceptance | Passed: all 12 cases in isolated fresh processes |
| Desktop/mobile axe scans | Passed with no serious or critical violations across eight populated routes per viewport |
| Base Compose configuration | Passed |
| Acceptance-override Compose configuration | Passed |
| `git diff --check` | Passed |
| Compose runtime and live smoke | Blocked: Docker socket absent |

The browser matrix used `/usr/bin/chromium` through
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` and `PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1`.
Each case ran in a fresh process because browser recycling in this host environment has produced
Chromium `SIGTRAP`/`SIGABRT` failures. Both 1440x1000 desktop and 390x844 mobile cases passed,
including the populated axe sweeps.

## Deterministic smoke coverage

Run the container-backed acceptance stack and smoke driver with:

```bash
docker network inspect contenthub_default >/dev/null 2>&1 || \
  docker network create contenthub_default
docker compose -f docker-compose.yml -f docker-compose.acceptance.yml \
  up -d --build --wait postgres api worker-source-generation worker-publishing scheduler frontend
python scripts/smoke.py \
  --base-url http://127.0.0.1:8000 \
  --provider fake \
  --telegram-mode dry-run \
  --output-dir ./smoke-results
docker compose -f docker-compose.yml -f docker-compose.acceptance.yml ps
```

The driver has one 300-second global deadline, reserves cleanup time, stops on the first failed
invariant, writes a mode-0600 secret-free JSON report, and restores the original automation
control even after failure. It creates a unique Persian brand, fake provider, public Telegram
source, unconfigured destination, and review-required route for every run.

The 13 ordered steps prove:

- API health and credential-free configuration;
- new-post-only activation at the fixture head and rejection of an out-of-range backfill;
- manual Persian intake and immutable evidence materialization;
- evidence-grounded fake research with claim citations;
- Telegram, Instagram, X, and blog generation;
- edit-invalidates-approval and hash-bound reapproval;
- dry-run album preservation for message IDs 42, 43, and 44;
- replay-safe duplicate-publish prevention;
- JSON, Markdown, HTML, and ZIP exports bound to the exact approved revisions;
- downloaded manifest, archive, and content bytes against their declared lengths and SHA-256 values;
- manual Instagram planning and completion of every server-returned checklist item;
- a pause-sensitive backfill remaining queued and unclaimed during global pause, then succeeding after resume;
- story, automation-route, and unfiltered pause history with no secret-canary leak;
- persisted worker/scheduler observations, queue counts, and dry-run control truth.

The acceptance-only Telegram transport is mounted only into `worker-source-generation`, requires
`APP_ENV=test`, serves the bundled album/media fixture without outbound requests, and is rejected
by settings validation in every non-test environment.

## Browser coverage

The 12 Chromium cases cover:

- the complete Persian/RTL newsroom flow at desktop and mobile sizes;
- review-first and explicitly confirmed automatic Telegram routes;
- manual URL/text intake plus standard, deep, and automatic research;
- global pause and retryable job recovery;
- ambiguous Telegram reconciliation without blind retry;
- all platform copy actions and the 14-file/download export projection;
- mobile navigation and horizontal-overflow checks;
- keyboard-only immutable edit and approval;
- serious/critical axe scans on Today, Inbox, Automations, Drafts, a populated draft, Calendar,
  Diagnostics, and Retention at both viewports.

## Recovery and security evidence

The full backend gate includes the following release-critical proofs:

- backup archives record and verify PostgreSQL, media, and export checksums and safe paths;
- restore requires explicit replacement confirmation and controls the actual split runtime services;
- recursive redaction removes credential canaries from logs, URLs, jobs, events, attempts, and API projections;
- an expired lease is recovered by a second worker with one durable job history;
- concurrent Telegram claims send once, and exact reconciliation replay creates one publication and event;
- provider, export, worker-heartbeat, and Telegram crash-window fault injection remains test-only and redacted.

No OpenRouter, Codex, Telegram MTProto, or Telegram publishing credential was supplied. Optional
credentialed smoke is outside the deterministic release gate and was not run.

## Environmental follow-up

When Docker is available, rerun the commands above and require all six services to be healthy or
running, then retain the generated `smoke-results/smoke-*.json` as the live container evidence.
Do not use `docker-compose.acceptance.yml` for deployment.
