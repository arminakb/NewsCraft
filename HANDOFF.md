# Handoff — NewsCraft (2026-07-25)

## Project at a Glance

NewsCraft is a FastAPI + PostgreSQL + Next.js news content platform that ingests RSS/Atom feeds and Telegram channels, normalizes and classifies content, supports evidence-backed research, multi-platform publishing (Telegram, Instagram, X, blog), and provides an operator dashboard with full editorial controls.

Branch: `armin` (pushed to `origin/armin`)
Base: `origin/main` (20 ahead, 0 behind)

## What's Been Built (Phases 1–9 + Content Settings)

The branch contains ~20 commits on top of main, scoped into these workstreams:

### 1. Worker & Job Infrastructure
- Worker isolation per capability (source/generation vs publishing) with leased job execution
- Terminal session isolation per job
- Capability gate — jobs declare capabilities, workers enforce boundaries
- Credential topology — each worker scope gets only the secrets it needs
- Job healthcheck with restart supervision (canary, readiness probes)
- Scheduler for source collection jobs; API mutation endpoints enqueue and return immediately

### 2. Security & Credential Management
- Encrypted secret store (`backend/app/security/secret_store.py`)
- Worker-scoped credential topology, enforced at runtime
- Authorization middleware with scope checking
- Outbound proxy policy (SOCKS5 for Telegram, direct for RSS/HTTP, configurable)
- Structurally redacted access logs (no leaked tokens in plaintext)

### 3. Telegram Publishing Lifecycle
- Full destination lifecycle (create, edit, enable/disable, recheck, delete, token rotation)
- Route management with multi-platform routing
- Content packs → drafts → approval → scheduled publishing
- Immutable editorial revisions
- Telegram bot health checks

### 4. LLM Provider & Editorial Settings
- Generic LLM provider connections (OpenAI-compatible, configurable per provider)
- Editorial profiles (per-provider system prompt, model selection, parameter overrides)
- Prompt governance — default prompts enforced, operator overrides audited
- Codex gateway — read-only MCP gateway for operator research
- `/settings/content` management surface (settings page in Next.js frontend)

### 5. Frontend Consolidation (Current)
- Articles API + collection management (backend + frontend)
- Legacy page redirects (`/inbox`, `/library`, `/media`, `/content` → flat `/articles` or `/feed`)
- Feed desktop e2e tests (842 lines)
- Component migration: deleted legacy library, manual-intake-dialog, research-panel, story-inbox
- Content settings page redesigned (1756 lines)

### 6. Observability & Operations
- Component health checks (API health, DB health, worker canary, Telegram connectivity)
- Operational health dashboard
- Readiness probes for Docker orchestration
- Backup/restore script
- Production-hardening validation smoke tests

## Architecture Highlights

```
docker-compose.yml          — PostgreSQL, API, frontend, workers (source, generation, publishing), scheduler
docker-compose.production.yml — production-grade compose with readiness checks
docker-compose.test.yml     — test-only compose
docker-compose.proxy.yml    — outbound proxy (SOCKS5) container
```

**Key directories:**

| Path | What |
|------|------|
| `backend/app/api/` | FastAPI route handlers (30 files) |
| `backend/app/security/` | Auth, middleware, scopes, secret store |
| `backend/app/jobs/` | Worker, scheduler, capability gate, healthcheck |
| `backend/app/codex_gateway/` | MCP server + credentials for read-only research |
| `backend/app/core/` | Config, logging, outbound proxy, secrets, faults |
| `backend/app/llm_providers/` | Generic LLM provider integration |
| `backend/app/publishing/telegram/` | Full Telegram publishing lifecycle |
| `backend/app/operations/` | Health checks, diagnostics |
| `backend/tests/` | 50+ test files across unit, postgres, integration |
| `frontend/app/` | Next.js app router pages |
| `frontend/features/articles/` | New articles page, collections, filter state |
| `frontend/features/settings/` | Content settings management UI |
| `frontend/tests/` | Frontend test suite |
| `docs/` | ADRs, implementation reports, audit findings |
| `docs/operations/` | Operator runbooks (backup, proxy, health, credentials) |

## Test Coverage

Backend tests (pytest):
- Unit tests: API routes, services, models, migrations
- Postgres-backed tests: 15+ files for API routes, gateway, publishing, worker boundary
- Integration tests: worker crash recovery, process crash handling
- Operations tests: health checks, backup/restore

Frontend tests (Vitest/Testing Library):
- ~15+ test files for components, pages, API mocks, redirects

E2E (Playwright):
- `frontend/e2e/feed-desktop.spec.ts` — comprehensive feed acceptance (842 lines)
- `frontend/e2e/telegram-automation.spec.ts`
- `frontend/e2e/full-platform-acceptance.spec.ts`

## Docker Quickstart

```bash
docker compose build
docker compose up -d postgres
docker compose up api          # starts after migration completes
docker compose up --build      # full stack: postgres, api, frontend, workers, scheduler
```

- Newsroom: http://127.0.0.1:3000
- API: http://127.0.0.1:8000

## Known Gaps & Not Yet Done

1. **Maintainability and UX debt** — the current cleanup, correctness, and operator-experience work is defined in `REFACTOR_PLAN.md`. Superseded execution plans have been removed.
2. **Frontend consolidation in progress** — `docs/frontend-consolidation/` has data contracts, wireframes, field maps for the Articles API migration, but the frontend `/articles` page is still being validated against the backend.
3. **`.sentry-native/`** — build directory owned by root, not part of the repo, fine to ignore.
4. **Multi-context docs** — `docs/agents/` defines how agents should consume this repo (AGENTS.md, issue-tracker.md, triage-labels.md, domain.md). If handoff recipient is another agent, those files define the conventions.

## Key Files to Read First

| File | Why |
|------|-----|
| `README.md` | Full project docs, structure, run instructions |
| `CONTEXT.md` | Domain glossary (classification terms) |
| `AGENTS.md` | Agent conventions for working in this repo |
| `REFACTOR_PLAN.md` | Current maintainability, correctness, and UX execution plan |
| `docs/operations/readiness-and-health.md` | Operational health runbook |
| `docs/production-readiness-audit-2026-07-15.md` | Full production hardening audit |
| `docs/frontend-audit/current-state.md` | Frontend audit findings |
| `docs/frontend-consolidation/data-contract.md` | Articles API data contract |
| `docker-compose.yml` | Full stack composition |
| `backend/pyproject.toml` | Python dependencies |

## Next Steps (Suggested)

1. Validate the articles API + collections API against the frontend (`backend/app/api/articles.py` + `backend/app/api/article_collections.py`)
2. Resolve frontend-backend contract drift per `docs/frontend-audit/`
3. Complete frontend consolidation — retire legacy pages, validate new `/articles` page
4. Deploy and smoke-test with `docker compose --profile production up`
5. Consider extracting the Codex gateway into its own deployable if read-heavy research traffic demands isolation
