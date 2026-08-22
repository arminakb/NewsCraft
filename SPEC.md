# NewsCraft — SPEC.md (Repository Architecture Memory)

> Written from actual source code (audit date: 2026-08-23). Every claim cites file + line.
> `UNKNOWN — requires implementation decision` markers flag things the repo does not answer.

## 1. System Architecture

### Frontend
Next.js 16 App Router, React 19, TanStack Query 5 (`frontend/components/providers/query-provider.tsx`).
- All backend calls go through a proxy route `frontend/app/api/backend/[...path]/route.ts` → `API_INTERNAL_BASE_URL ?? http://localhost:8000`; strips client-controlled principal headers.
- Fetch wrapper `frontend/lib/http.ts` (`API_BASE_URL = /api/backend`).
- Types generated from OpenAPI: `npm run api:generate` → `lib/api/generated.ts` from `contracts/openapi.json`, camelized via `lib/camelize.ts`.
- Feature modules under `frontend/features/` (settings, automations, editorial, review…).

### Backend
FastAPI under `backend/app/`, async SQLAlchemy + PostgreSQL, Alembic migrations in `backend/alembic/versions/`.
- Routers mounted in `app/api/routes.py`. Security middleware maps routes to scopes (e.g. `llm-providers` → `providers:write`) in `app/security/middleware.py:75`.
- Startup seeding in `app/main.py:29-32` (`seed_default_telegram_prompt`, `seed_default_editorial_prompts`, telegram config) — idempotent, advisory-locked.

### PostgreSQL responsibilities
Durable workflow state only: automations/versions/runs/node-runs, jobs queue, research runs, generation runs/packs/revisions, prompt templates/versions, LLM providers + encrypted secrets.

### Worker responsibilities
`app/jobs/worker.py` — `WorkerRunner.run_once()` (:324): claim job (lease+heartbeat) → run handler in isolated session → terminal finish/fail. Capability-scoped workers (`--capability ingestion|source|generation|publishing`, :246). Job→handler registry: `app/jobs/registry.py:54-183`.

### Workflow execution model
Workflows = **Automations**. Graph is a JSONB column on immutable `AutomationVersion` ("snapshot": `graph`, `graph_hash`, `compiled_plan`, `validation_summary`; DB trigger enforces immutability). Execution = `AutomationRun` + per-node `AutomationNodeRun` rows; nodes hand off via **durable artifacts**, not memory: each handler persists output and a wrapper queues the next node's job (`definitions/runtime_state.py:108-276`). Node-to-node payloads use `WorkflowArtifact[T]` envelope (`definitions/schemas.py:76-91`).

### API boundaries
Settings/providers/prompts/workflows all REST under one FastAPI app; frontend never talks to providers' credentials (only opaque status/readiness fields come out).

### Settings architecture
Six sections registered in `frontend/features/settings/settings-sections.ts:14-63`: llm-providers, codex, telegram, date-time, retention, prompts. Backend sources of truth: `app/api/llm_providers.py`, `app/api/generation_settings.py` (prompts), operator_settings/content/retention endpoints.

### Automation architecture
`AutomationDefinitionService` (create/version/restore/validate), compiler (`compiler.py` → `compiled_plan` + hash, drift-checked at run start via `verify_compiled_plan()`), execution service (`execution.py:239-312` start; dry_run default true skips publishing nodes), review gate (`POST /automation-runs/{id}/review/approve`).

### Node architecture
Node registry `app/automations/definitions/registry.py:272-484`. Node types: `manual`, `collection_article_added`, `new_source_item`, `schedule`, `select_content`, `filter_content`, **`research`**, **`generate_content_pack`**, `validate`, `human_review`, `save_drafts`, `manual_package`, `telegram_publish`.
Each node has a frozen Pydantic `config_model` (`extra="forbid"`) validated at save time (`validation.py:134-183`) and served to the UI as JSON Schema via `GET /automation-node-catalog` — the node config form is schema-driven from the backend catalog (`workflow-inspector.tsx:103-122`).

## 2. Provider Architecture

### Model
`LLMProvider` table `llm_providers` (`app/llm_providers/models.py:14-78`): name (unique), protocol check-constrained to `'openai_compatible'|'fake'`, base_url, default_model, **`enabled` bool default false**, `secret_id` FK → `encrypted_secrets` (ON DELETE RESTRICT), settings JSONB (must contain `pricing` + `research_budgets` for openai_compatible), health/capability status: `health_status` (`unchecked|healthy|degraded|unhealthy`), `generation_capability`, `research_capability` (`unknown|ready|unavailable`), `failure_code/message`, test timestamps/latency, `ownership` (`system_managed|operator_managed`).
Credentials: AES-GCM encrypted `EncryptedSecret` rows (`app/security/models.py:13-31`, store `secret_store.py:214-333`, AAD-bound, scope-gated `providers:write`/`providers:read`).
Shadow row: every operator provider keeps a synchronized legacy `AIProviderProfile` row in `ai_provider_profiles` (`generation/models.py:95-110`, sync at `llm_providers/service.py:335-346`, same UUID). Run tables reference this shadow id (`GenerationRun.provider_profile_id`, `ResearchRun.provider_profile_id`, `AutomationRoute.ai_provider_profile_id`).

### API endpoints (`app/api/llm_providers.py`)
- `GET/POST /llm-providers`, `GET/PATCH /{id}`, `POST /{id}/rotate-secret`, `POST /{id}/test`, `POST /{id}/enable|disable`, `GET /{id}/dependencies`, `DELETE /{id}` (204, dependency-guarded).
- Create is allowed with any state; creating already-enabled non-fake is rejected (`service.py:363-364`).
- Responses include computed readiness: `configured`, `generation_ready`, `research_ready`, `ready_for_enablement`, `readiness_code/message`.

### Test flow (THE core problem)
`service.test_connection` (`service.py:467-544`) runs two real model probes. On failure:
```python
provider.health_status = "unhealthy"; generation_capability = "unavailable"
research_capability = "unavailable"; failure_code = ...; provider.enabled = False
```
Test endpoint returns **503** when `generation_capability != "ready"` (`api/llm_providers.py:197-204`). Degraded (research fails, generation OK) still allows enablement.
Enable requires `provider_readiness` = generation ready **and fresh successful test within TTL (default 3600s)** else 409 `llm_provider_not_ready` (`readiness.py:61-99`, codes `test_required`/`test_stale`).

### What prevents a provider from being used by workflow nodes (exact gates)
1. Workflow editor provider options are fetched from `GET /telegram/automations/options` (`telegram_automations.py:207-300`), which appends a profile only if `shaped["generation"]` capability is truthy (:244) — an untested or failed provider **never appears in the selector**, even though its record exists.
2. Enablement gate above (fresh passing test mandatory).
3. Runtime resolver re-checks capability: `ProviderProfileResolver.resolve_with_session` (`generation/providers/profiles.py:290-363`) calls `provider_capability_ready`; fake protocol short-circuits to the registry fake provider; openai_compatible decrypts `EncryptedSecret` with scope `providers:read`.
4. Legacy "Deterministic Fake" profile hidden from options server-side (`generation_settings.py:419-437`).

### How workflow nodes reference providers
Node config field `provider_profile_id: UUID` on `ResearchConfig` (registry.py:83-88) and `GenerateContentPackConfig` (:91-102); required-resource enforcement `_REQUIRED_RESOURCE_FIELDS` (`validation.py:48-55`). Persisted inside graph JSONB → snapshot → compiled plan → job payload → runtime resolution (§4/§9 of audit).

### Frontend flow
`features/settings/llm-providers-section.tsx` + `content-settings-api.ts:63-113` (list/create/edit/test/enable/disable/rotate/delete, dependencies guard). Cards filter out `protocol === "fake"` (:191). Workflow editor select feeds from `/telegram/automations/options` (`features/automations/telegram-api.ts:74-94`); field label comes from Pydantic JSON-Schema title → **"Provider Profile Id"** (`workflow-inspector.tsx:196,244-264`). No hardcoded provider lists exist in the frontend today.

## 3. Prompt Architecture

### Models (`app/generation/models.py`)
- `PromptTemplate` (`prompt_templates`, :43-55): `purpose_key` **globally unique** — one template per purpose; `name`, `description`.
- `PromptTemplateVersion` (`prompt_template_versions`, :58-92): immutable versions with `system_template` (≤20k), `user_template` (≤40k), `output_schema(_version)`, `checksum_sha256`, exactly-one-active partial index, activation audit columns (added by migration `0017_prompt_governance.py`).

### API (`app/api/generation_settings.py`)
`GET/POST /prompt-templates`, `POST /prompt-templates/{id}/versions` (immutable), `GET .../versions`, `POST /prompt-template-versions/{version_id}/activate` (reason ≥3 chars required). Activation deactivates siblings, stamps actor/time (:406-411).

### Bundled packages
Seeded at startup (`default_prompts.py`): purposes `telegram_rewrite`, `canonical_story`, `telegram_pack`, `instagram_pack`, `x_pack`, `blog_pack`. Arbitrary new `purpose_key`s are accepted by POST but get **no variable validation and empty output schema** (`generation_settings.py:330-331`) — i.e., free-form templates exist structurally but are second-class. Variable whitelist enforced via `string.Formatter` parse (`default_prompts.py:177-204`); unknown/missing variables → 422.

### References inside workflow nodes
Only `generate_content_pack` references prompts: `prompt_version_ids: list[UUID]` (≤10) + `prompt_checksums: dict[UUID, sha256]` that must match exactly (registry.py:98-102 validator). The **research node has no prompt reference at all** today.

### Validation/resolution chain
Save-time resource checks: deleted prompt → `resource_missing`, inactive version → `prompt_version_inactive` finding (`definitions/resources.py:116-126,273-289`); checksum drift → error finding (`service.py:690-717`). At run start `require_exact_generation_prompts` (`execution.py:142-185`) demands pinned versions be *exactly* the active set for `{canonical_story} ∪ platforms`, else 409. Runtime locks the active version row and re-verifies id+checksum (`generation_helpers.py:155-192`), re-checking before each provider call (`package_generation.py:163-168`).

### Prompt storage/composition
Templates have separate `system_template` and `user_template` — system instructions and runtime input are already separated at persistence time. Runtime composes the final request intentionally.

## 4. Workflow Architecture

- **Workflow model**: `Automation` + `AutomationVersion` (snapshot) (`definitions/models.py:25-107`).
- **Node model**: JSON graph (`WorkflowGraphV1`: entry_node_id, ≤30 nodes, ≤60 edges; `WorkflowNode{id,type,config}` — schemas.py:154-194).
- **Config schema/validation**: per-type Pydantic models in registry; validated save-time (`validation.py:156-168`), errors become blocking findings `node_config_invalid`; forbidden-secret key scan (:26-46). Required resources enforced per type.
- **Snapshots**: immutable `AutomationVersion` + `compiled_plan`; plan-hash drift rejected at run start (`compiler.py:192-218`).
- **Execution/runtime**: job engine (`jobs/models.py`, `worker.py`); run start creates run + node-run rows, enqueue first job; wrapper advances nodes and queues continuations (`runtime_state.py`); research→generate handoff via durable `StoryRevision` + evidence links, generate→review via `ContentPack`/`PlatformVariantRevision` (`approval_state="pending_review"`).
- **AI Research node** (`research/handlers.py:382-647`): config `{provider_profile_id, mode, query_budget(1-10, def 3), page_budget(1-50, def 10), time_budget_seconds(10-600, def 120)}` — but budgets are **validated-only**: authoritative values come from the provider's `settings.research_budgets` (`research/service.py:126-176` stamps them onto `ResearchRun`), and node-vs-provider budget drift is rejected by `_validate_job_binding` (handlers.py:116-144). In-loop enforcement lives in `openrouter_loop.py:259-296` against the `ResearchBudget` contract; termination metadata via `budget_exceeded()` (`research/base.py:69-87`).
- **AI Generate node** (`generation/package_generation.py`, canonical handler `canonical_generation.py`): consumes locked story revision + evidence snapshots; produces per-platform revisions pending review.
- **Input/output passing**: research output = `ResearchResult{output: {sources[], brief}, usage, elapsed_ms, sanitized_events}` (`research/base.py:31-61`, schemas.py:72-121: evidence-keyed sources with sha256, brief with verified_facts/disagreements/missing_information/suggested_angles + citations). Materialized as immutable `StoryRevision` before generate reads it.

## 5. Relevant Files

| Concern | Backend files | Frontend files | Tests |
| ------- | ------------- | -------------- | ----- |
| LLM provider model/service | `backend/app/llm_providers/{models,service,readiness,schemas}.py` | `frontend/features/settings/llm-providers-section.tsx`, `content-settings-api.ts` | `backend/tests/api/`, `backend/tests/test_llm_providers*.py` |
| Provider API | `backend/app/api/llm_providers.py` | — | `backend/tests/api/test_llm_providers*` |
| Secrets/crypto | `backend/app/security/{models,secret_store}.py` | — | security tests |
| Shadow profiles | `backend/app/generation/models.py` (AIProviderProfile), `llm_providers/service.py:_shadow` | `features/editorial/api.ts` | — |
| Provider options for workflows | `backend/app/api/telegram_automations.py:207-300` | `features/automations/telegram-api.ts:74-94`, `workflow-inspector.tsx` | — |
| Prompts model/API | `backend/app/generation/{models,default_prompts}.py`, `api/{generation_settings,generation_schemas}.py` | `features/settings/prompt-governance-section.tsx`, `telegram-api.ts`, `telegram-types.ts` | `test_generation_settings_api.py`, `test_default_prompts.py`, `test_prompt_governance_migration.py` |
| Workflow definitions/validation/compiler | `backend/app/automations/definitions/{models,schemas,validation,compiler,registry,resources,service,execution,runtime_state,handler_wrapper}.py` | `features/automations/{automation-builder,workflow-canvas,workflow-inspector,node-customize-dialog,workflow-config-schema,automation-api}.tsx/ts` | `test_automation_compiler.py`, api tests |
| Job engine/worker | `backend/app/jobs/{models,worker,registry}.py` | — | integration tests |
| AI Research | `backend/app/research/{handlers,service,schemas,base,fake,openrouter_loop,codex_adapter,continuations}.py` | inspector generic fields | `backend/tests/generation/`, research tests |
| AI Generate | `backend/app/generation/{package_generation,canonical_generation,provider_execution,generation_helpers,providers/*}.py` | variant-editor | generation tests |
| Review boundary | `backend/app/workflows/states.py`, `generation/review_decisions.py`, `runtime_state.py` review approve | `features/review/` | approval tests |
| Migrations | `backend/alembic/versions/0004,0012,0013,0016,0017,0027,0038_*.py` | — | `test_prompt_governance_migration.py` |
| Acceptance/dry-run | `docker-compose.acceptance.yml`, `worker.py:155-165`, `execution.py` dry_run | — | acceptance suite |

## 6. Current Problems

1. **Provider unusability loop (TASK 1 core).** A newly created provider starts `unchecked`/`unknown`; it appears nowhere in the workflow editor because options filter on generation capability; testing requires real connectivity; failed test force-disables and marks capabilities unavailable. Net effect: without a passing live test, a provider can neither be enabled nor selected — `provider_profile_id` is dead weight for normal config. Only the fake protocol bypasses everything.
2. **Enable semantics conflate existence with readiness.** `enabled=false` is both "operator turned it off" and "test hasn't passed", and a failed test mutates the record (`enabled=False`) rather than just recording health.
3. **Prompt system is package-shaped, not user-shaped (TASK 2 core).** One-template-per-purpose with globally unique `purpose_key`, seeded bundles, variable whitelists, and exact-active-set pinning make user-defined reusable prompts second-class; there is no concept of a user-authored general-purpose system prompt selectable by nodes.
4. **Research node cannot reference a system prompt** — no prompt field on `ResearchConfig` at all.
5. **Budgets are decorative on research nodes (TASK 3 core).** `query_budget/page_budget/time_budget_seconds` validate and render in the UI, but runtime values come from provider `settings.research_budgets`; node values are ignored (drift even rejected). UI shows budgets that don't do anything.
6. **UI label wrong:** schema title renders "Provider Profile Id"; TASK 1 requires "LLM Provider".
7. Options endpoint coupling: workflow provider list piggybacks on `/telegram/automations/options` — works, but is an odd source for a non-telegram concern (acceptable to keep; not duplicated registries).

## 7. Intended Architecture

After Tasks 1–3:
- **Providers**: existence ≠ readiness. Creating/updating a provider always succeeds structurally; test results land in health/capability columns only. Enable stays gated on readiness (runtime safety), but **selection for configuration uses a canonical backend list** (existing `/llm-providers` + computed availability flags — no second registry). Workflow editor consumes that list dynamically; label becomes "LLM Provider". Runtime keeps strict validation: unresolved/unready provider ⇒ clear PermanentError at the correct boundary.
- **Prompts**: user-defined reusable system prompts become first-class configuration resources creatable in Settings → Prompts, listed by a backend endpoint, selectable by every LLM node (research + generate). System-prompt content stays separate from runtime input (already true: `system_template` vs runtime article input). Bundled seed packages stop being the center of the prompt UX while historical data/migrations stay intact. Exactly two example starter prompts ship as data through the same public mechanism (no special runtime path).
- **Research node config**: exactly five operator-facing fields — LLM Provider, System Prompt, Query Budget, Page Budget, Time Budget — validated authoritatively backend-side and actually honored by runtime, with graceful budget-exceeded metadata already produced by `budget_exceeded()`.
- Chain: `Settings(provider,prompt) → node config refs (UUID+checksum where applicable) → AutomationVersion snapshot → compiled plan → job payload → runtime resolve (decrypt secret w/ `providers:read`, lock active prompt version, enforce budgets) → structured research → StoryRevision → generate → pending_review → human approval → publish (separate jobs)`.

## 8. Production News Pipeline

```
Content Item (source/feed)
  → [trigger node] → select/filter
  → AI Research node
      • provider_profile_id → resolved at runtime via ProviderProfileResolver (fake ⇒ deterministic backend; openai_compatible ⇒ decrypt EncryptedSecret)
      • prompt ref → resolved/locked active version (system instruction)
      • query/page/time budgets → enforced in-loop; stop reason recorded
      • output: sources(evidence_key,url,sha256,content) + brief(summary,verified_facts,disagreements,missing_information,angles,citations)
  → StoryRevision (immutable, evidence-linked)
  → AI Generate node
      • provider_profile_id resolved likewise
      • prompt_version_ids (+checksums) pinned to exact active set
      • input = original article context + locked story revision + evidence
      • output: PlatformVariantRevision(s), approval_state="pending_review"
  → human_review node (waiting_for_review; structural guarantee: publish requires exact Human Review ancestor — validation.py:541-553)
  → editorial approve (hash-checked, revalidated) 
  → telegram_publish / save_drafts / manual_package (separate publishing jobs; skipped in dry_run)
```

Resolution points:
- **provider profile**: node config → snapshot → job payload → `resolve_with_session` (profiles.py:290-363).
- **system prompt (research)**: NEW — node config ref → runtime lock of active version. UNKNOWN — requires implementation decision: whether research prompt reuses `prompt_templates`/`prompt_template_versions` (with a new purpose convention) or a dedicated table; reuse is preferred per global rules.
- **system prompt (generation)**: existing `prompt_version_ids`+`prompt_checksums` pinning, exact-active-set rule.
- **query/page/time budgets**: node config must become authoritative (TASK 3), replacing provider-settings-derived defaults at request time.
- **article input**: content item/story supplied by automation run payload (`AutomationRunStart.story_id`), composed as runtime user-input — never concatenated into stored prompt text.
- **structured output**: `CandidateResearchBrief`/`DiscoveredSourcePayload` schema (canonical; no parallel format).
