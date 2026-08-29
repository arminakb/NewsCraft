# REPORT.md — NewsCraft Production-Readiness (Settings → Workflow → Runtime)

Audit date: 2026-08-23. Companion to `SPEC.md` and `TASK.md`.

## 1. Executive Summary

**Yes — the chain is production-ready for the deterministic fake-provider path, and structurally ready for live providers.**

After Tasks 0–3, a provider profile created in Settings is selectable by every LLM workflow node regardless of connectivity-test state; users can create reusable system prompts in Settings and pin them into AI Research and AI Generate nodes; the AI Research node exposes exactly LLM Provider / System Prompt / Query Budget / Page Budget / Time Budget, and those budgets are now authoritative at runtime with termination metadata. The full pipeline `article evidence → AI Research → structured research → StoryRevision → AI Generate → pending_review` executes end-to-end under a new integration test (`tests/postgres/test_news_production_pipeline.py`) with zero publishing side effects.

Remaining issues are pre-existing test-infra flakes and one pre-existing broken unit test (§8); none block the operator chain.

## 2. Verified Flows

| Flow | Evidence |
| ---- | -------- |
| Provider created via `POST /llm-providers`, listed, never leaks API key | `tests/postgres/test_llm_providers_api.py` (pre-existing), `test_news_production_pipeline.py` asserts 201 + key absence |
| Untested/failed provider selectable & savable; blocked before run | `test_provider_workflow_selection.py` (3 tests) |
| Failed connectivity test keeps record usable; enable still 409 | `test_failed_connectivity_test_keeps_provider_usable_for_configuration` |
| Node catalog labels: `LLM Provider`, `System Prompt`, `Query Budget`, `Page Budget`, `Time Budget` | catalog assertions in both postgres test files |
| Two starter prompts seeded idempotently (`News Article Research — Structured Evidence`, `News Article Generation — Evidence-Based Editorial Post`) | `test_starter_prompts_seed_two_reusable_user_editable_prompts` |
| User-defined prompt creation without `purpose_key` (server-derived slug) | `POST /prompt-templates` schema change + existing settings API tests |
| Research node pins active prompt w/ checksum; drift reported at validate; runtime re-verifies | `test_validate_reports_wrong_research_prompt_checksum`, `_resolve_payload_system_prompt` tests |
| Node budgets override provider defaults on `ResearchRun` (query=2/page=4/time=120) | `test_research_node_persists_prompt_and_node_budgets_into_run`, E2E reload assertion |
| Full chain: Settings APIs → save → reload → run → research_story → generate(+telegram) → pending_review, no publish jobs/publications | `test_settings_to_reviewable_news_post_pipeline` |
| Safety policy composes first with user system prompt | `test_compose_system_policy_keeps_safety_policy_first` |
| Budget termination metadata | `tests/research/test_research_budget_metadata.py` (3 tests) |

## 3. Provider Findings

- **Lifecycle**: create/update/delete unchanged and safe. A failed test still records `unhealthy/unavailable` and force-disables — kept intentionally as *executability* state; it no longer affects *configurability*.
- **Enable/test behavior**: enablement gate untouched (fresh passing test within TTL required) — this is the explicit runtime-safety architecture.
- **Workflow integration**: the editor's provider select now consumes canonical `GET /llm-providers` (all profiles, any health state). Readiness badges come from `/automation-resource-catalog`. The old capability-filtered `/telegram/automations/options` remains only for legacy Telegram-route UI.
- **Runtime resolution**: unchanged and strict — run-start validation 409s when resources are not ready; `ProviderProfileResolver.resolve_with_session` re-checks capability and decrypts secrets with scope `providers:read`; node execution fails with `PermanentJobError` as final backstop.
- **Credentials/security**: no secret material appears in options payloads, graphs, snapshots, or logs (asserted by existing redaction tests + `"api-secret-canary" not in response.text` checks).

## 4. Prompt Findings

- **Storage**: reused `prompt_templates`/`prompt_template_versions` (immutable versions, one-active partial index). No migration needed; historical data intact. Bundled packages remain seeded for the generation contract purposes but are no longer the Settings UX center; the UI lists **all** backend templates dynamically and supports creating new ones (optional `purpose_key`, server-side slug).
- **Selection**: generate nodes keep `prompt_version_ids`+checksums (exact-active-set rule); research nodes gained `prompt_template_version_id`+`prompt_checksum_sha256`.
- **Persistence**: references ride graph JSONB → snapshot → compiled plan → job payload; E2E test reloads version 1 and asserts every selection survives byte-for-byte semantics.
- **Runtime resolution**: request boundary verifies existence+active+checksum (`_resolve_prompt_reference`); handler re-verifies against locked row (`_resolve_payload_system_prompt`) before composing the model request. System prompt stays configuration; article/story input stays runtime user content.
- **Versioning/reference issues**: deleted template → `resource_missing` error finding (save-blocking only if referenced resource truly absent — verified states `unavailable/not_configured/disabled` behave as designed). Checksum drift → dedicated findings + `research_prompt_checksum_mismatch` permanent job error.

## 5. AI Research Findings

- **Configuration**: exactly five operator fields (+ internal mode), titles served from backend JSON Schema — single source of truth.
- **Budget enforcement**: node budgets now override the provider-derived `ResearchBudget` (`max_queries/max_pages/max_elapsed_seconds`), stamped onto `ResearchRun`, embedded in the job payload, and re-derived identically in the handler so the existing drift check (`_validate_job_binding`) stays meaningful. In-loop enforcement (`openrouter_loop._check_*`, `_record_exhausted`) and the post-hoc `budget_exceeded()` trust boundary apply to the effective budget.
- **Output structure**: canonical `CandidateResearchBrief`/`DiscoveredSourcePayload` schema unchanged — materialized as immutable `StoryRevision` with evidence links; AI Generate consumes the revision, not raw JSON.
- **Runtime behavior**: success result now carries `budget_termination` metadata (`termination_reason`, `queries_executed`, `pages_inspected`, `elapsed_ms`) projected into node output summaries. Mid-run query/page exhaustion degrades gracefully via `_record_exhausted` observations rather than failing.

## 6. AI Generate Findings

- **Input contract**: extended `GeneratePackRequest` with research prompt/budget passthrough fields; continuation payload model updated accordingly.
- **Research integration**: fixed a **pre-existing HEAD bug** — `request_pack.py` embedded `generation_provider_configuration_revision/checksum` into the continuation that `ContentPackContinuationPayload` (extra=forbid) rejected, breaking every research→generate handoff. Fields added; normalization uses `exclude_none` so stored legacy continuations stay stable.
- **Prompt integration**: exact-active-set pinning unchanged; starter generation prompt is an ordinary editable template with no special runtime path.
- **Output contract**: per-platform revisions land `approval_state="pending_review"`; hash-checked approval flow untouched.

## 7. End-to-End Findings

`article → research → generation` **works**, proven by `test_settings_to_reviewable_news_post_pipeline`: Settings APIs create provider+prompts; workflow saves and reloads with all selections; dry-run start enqueues `research_story` (fake backend honors pinned prompt + budgets); continuation hands off to `content_pack.generate(_telegram)`; revisions exist as pending review; publish queue and publications remain empty.

## 8. Remaining Problems

All previously listed problems are fixed (2026-08-24) except working-tree hygiene, which stays an owner decision.

| Severity | Component | Status | Resolution |
| --- | --- | --- | --- |
| MEDIUM | `backend/tests/postgres/test_multiplatform_pack_durability.py` | **Fixed** | Patched symbol renamed `_invoke` → `invoke` (matches post-`6c44ff5` API); test passes against Postgres. |
| MEDIUM | Frontend unit suite under full parallel load | **Fixed** | `vitest.config.ts` now caps `maxWorkers: "50%"`; three consecutive full runs: **606 passed / 0 failed** each. |
| LOW | `e2e/automation-workflow-builder.spec.ts:82` focus flake | **Fixed** | Focus restore in `node-customize-dialog.tsx` now polls (≤10 × 50ms) until the final React Flow node owns focus instead of a single `setTimeout(0)`; builder spec passes 2× consecutively. |
| LOW | `research/codex_adapter.py` system prompt | **Fixed** | Saved research system prompt is composed (safety policy first, via shared `compose_system_policy` moved to `research/prompts.py`) above the codex task input; covered by two new adapter tests. No-prompt behavior unchanged. |
| LOW | Working tree hygiene | Open | Pre-session uncommitted changes (`TASK.md`, fake-stub hiding + tests, untracked `docker-compose.local.yml`) remain for owner review/commit. |

Note: one intermittent failure of the Test Studio spec (`automation-workflow-builder.spec.ts:473`) was observed once during verification; it passes at both the pre-change baseline and with current changes across repeated runs and is treated as environment flake, not regression.

## 9. Evidence

Commands actually executed (working dir noted):

- Backend affected suites: `cd backend && TEST_DATABASE_URL=…newscraft_test uv run python -m pytest tests/research tests/generation/test_editorial_service.py tests/postgres/{test_research_prompt_and_budgets,test_provider_workflow_selection,test_automation_execution,test_automation_definitions}.py … -q` → **267 passed**
- Full backend suite: `TEST_DATABASE_URL=… uv run python -m pytest tests -q` → **2289 passed, 5 failed**; all 5 diagnosed: openapi contract (fixed by regenerating `contracts/openapi.json` after `purpose_key` became optional), 3 collection-trigger flakes (pass individually), 1 pre-existing durability monkeypatch breakage (§8).
- New E2E: `uv run python -m pytest tests/postgres/test_news_production_pipeline.py -q` → **1 passed**
- Quality gates: `scripts/quality_baseline.py --check` → initially ruff 8 / mypy 4 findings; fixed in `fix:` commit; now **mypy: Success (298 files)**, **ruff: all checks passed**
- Frontend: `npm run typecheck` → exit 0 · `npx vitest run tests/` → 605–606 passed with rotating load flakes (baseline without changes also fails ~5) · targeted suites pass clean · `npm run build` → success
- E2E Playwright: `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome-stable npx playwright test e2e/theme.spec.ts e2e/automation-workflow-builder.spec.ts --workers=1` → **11 passed, 1 failed** (pre-existing focus flake, §8). Full-suite run aborted: `/usr/bin/chromium` missing on host; managed browsers present but specs require the documented env var.
- Runtime observation: research job executed against `EvidenceGroundedFakeResearchBackend` inside E2E produced a succeeded `AutomationRun` with structured brief → StoryRevision → telegram revision pending review.

## 10. Recommended Next Steps

1. ~~Fix the broken multiplatform-durability unit test~~ — done (`_invoke` → `invoke`).
2. ~~De-flake CI: cap vitest workers; make the builder e2e focus assertion retry-tolerant~~ — done (`maxWorkers: "50%"`, polling focus restore).
3. ~~Pass saved system prompts through the legacy codex research adapter~~ — done via shared `compose_system_policy` in `research/prompts.py`.
4. Consider promoting the research-prompt integrity codes (`research_prompt_*`) into operator-facing recovery actions like the generate equivalents.
5. Decide ownership of the pre-existing uncommitted fake-stub-hiding changes and commit or discard them.

Verification (2026-08-24): quality baseline exit 0 · mypy 298 files clean · `npm run typecheck` + `npm run build` pass · vitest 606×3 runs green · builder Playwright spec 10/10 twice · `tests/research` + provider contract suites + postgres durability/prompt suites all pass.
