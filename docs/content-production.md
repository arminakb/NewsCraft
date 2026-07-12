# Content Production Architecture

NewsCraft's content-production feature is an event-driven backend pipeline for producing evidence-grounded Persian Telegram packages. It is isolated under `backend/app/content_production/` and uses the existing FastAPI, SQLAlchemy, PostgreSQL, and Alembic stack.

## Workflow

```text
API
→ durable outbox
→ WorkflowEventWorker
→ typed EventDispatcher
→ traced production handlers
→ deterministic, idempotent artifacts
→ human shortlist approval
→ human final-package approval
→ Telegram dispatch handoff
```

Creating a request commits the request and its first outbox event atomically. The worker claims pending events with PostgreSQL row locking, dispatches one typed handler at a time, and records bounded retries. Handler savepoints keep domain mutations, canonical artifact creation, outgoing events, and trace finalization consistent.

The item path is:

1. select and rank candidates;
2. wait for explicit human shortlist approval;
3. evaluate content sufficiency;
4. when needed, safely extract the source article and perform bounded enrichment, then re-check sufficiency;
5. create an evidence-grounded editorial brief;
6. generate one Persian Telegram draft;
7. evaluate quality against the persisted rubric;
8. resolve existing media or a null/unavailable image-generation result;
9. build the Telegram package;
10. wait for explicit human final approval; and
11. create a non-publishing dispatch request.

Routing is bounded: extraction and enrichment are attempted at most once in the sufficiency path, and unresolved insufficiency produces a terminal workflow failure. Artifact IDs derive from causal event identity and immutable discriminators so replay returns the canonical row instead of duplicating provider calls or outputs.

## Module Boundaries

- `events.py`, `states.py`, and `orchestration.py` define event vocabulary, state policy, dispatch, and worker behavior.
- `handlers.py` composes domain services and owns event-to-event workflow transitions.
- `repository.py`, `idempotency.py`, and `tracing.py` contain persistence, canonical artifact, and execution-trace mechanics.
- `candidates.py`, `sufficiency.py`, `briefs.py`, `telegram_drafts.py`, `quality.py`, `media.py`, `packages.py`, and `dispatch.py` implement explicit feature steps.
- `evidence.py` keeps evidence selection and relevance rules independent from HTTP transports.
- `enrichment.py` defines extraction/enrichment contracts and application services; `providers.py` contains the safe network adapters and provider construction.
- `llm.py` owns the bounded LLM request/response contract, schemas, OpenAI Responses transport, and OpenRouter Chat Completions transport.
- FastAPI routes produce commands and expose approval/artifact contracts; they do not run the production chain synchronously.

The package uses explicit dependency injection through dispatcher handler options and `build_production_provider_options`. There are no wildcard imports, path manipulation, generic framework layers, or duplicate publishing interfaces.

## Database Migrations

Migrations `0004_content_production_foundation` through `0016_persian_llm_generation` form one linear, reversible chain after `0003_content_intelligence_schema`. Apply them before starting API or worker processes:

```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/alembic heads
.venv/bin/alembic current
```

Both `heads` and an upgraded database should report `0016_persian_llm_generation`.

## Provider Configuration

Safe local and CI defaults disable live search and LLM calls:

```text
ENRICHMENT_PROVIDER=none
LLM_PROVIDER=none
OPENAI_API_KEY=
OPENROUTER_API_KEY=
```

For direct OpenAI Responses generation, set `LLM_PROVIDER=openai`, an OpenAI API base URL/model, and `OPENAI_API_KEY` in the process environment. For OpenRouter structured Chat Completions, set `LLM_PROVIDER=openrouter`, `LLM_BASE_URL=https://openrouter.ai/api/v1`, an OpenRouter model, and `OPENROUTER_API_KEY` in the process environment.

The OpenRouter adapter uses non-streaming `/chat/completions` with strict JSON Schema output. The OpenAI adapter uses `/responses`. Both preserve the same operation schemas and evidence-grounding checks. Provider failures are mapped to bounded retryable or permanent codes without storing credentials, authorization headers, raw response bodies, assistant content, refusal text, prompts, or hidden reasoning.

`ENRICHMENT_PROVIDER=duckduckgo` enables bounded public-web search. Article extraction rejects unsafe destinations, private network addresses, unsupported content types, oversized bodies, and excessive redirects.

## Human Gates And Publishing Boundary

Candidate processing cannot begin until a human approves a specific shortlist execution. A completed package cannot create a dispatch request until a human explicitly approves that package. Rejection and revision paths remain explicit API commands and traced decisions.

The dispatch service creates a database handoff only. There is no Telegram publishing adapter or send action, and automated validation must never introduce one.

## Validation

Start PostgreSQL, upgrade migrations, and run checks without live provider credentials:

```bash
docker compose up -d postgres
cd backend
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@localhost:5432/newscraft \
  .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@localhost:5432/newscraft \
  .venv/bin/python -m pytest -p no:cacheprovider -q
.venv/bin/ruff check --no-cache .
.venv/bin/alembic heads
.venv/bin/alembic current
```

The test suite uses fakes and `httpx.MockTransport` for provider behavior. It must not call OpenAI, OpenRouter, DuckDuckGo, Telegram, or image-generation services.

## Current Limitations

- Deterministic and mocked OpenRouter Chat Completions integration is validated, but the live OpenRouter canary has not completed successfully.
- Offline Persian product-quality fixtures succeeded; the full live three-item pilot remains pending.
- Image generation may be unavailable and use the null-provider path.
- Telegram publishing is intentionally disabled; only the dispatch handoff is persisted.
- Client-supplied command idempotency keys remain future work where callers need stable identities across separate HTTP retries.
