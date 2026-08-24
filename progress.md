# TestSKILL.md Phase 1 progress

## 2026-08-23T21:55Z — Step 0 Environment up
- Did: started full compose stack with local override (`docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d`); override exists because the default network subnet collides with the VPN (172.19/16).
- Result: pass
- Evidence: `/health/ready` reports `schema_current` + `database_connected`; api/frontend/workers/scheduler healthy on newscraft_local_net.

## 2026-08-23T21:28Z — Step 1 Article collection
- Did: `POST /article-collections` (needs browser-like `origin: http://127.0.0.1:3000`, else 403 origin_validation_failed).
- Result: pass
- Evidence: collection `25a230be-dac1-467d-a750-8427173c1e14`.

## 2026-08-23T21:28Z — Step 2 Source collection
- Did: reused existing sources (44 present, no seeding needed); selected 5 healthy AI-news RSS sources; created source collection via bulk API.
- Result: pass
- Evidence: collection `af2fdc1a-eaa6-4d60-89c2-175da99ffcc1` (AWS ML, HuggingFace, OpenAI News, The Decoder, VentureBeat AI).

## 2026-08-23T21:32Z — Step 3 Settings dependencies
- Did: internet available; tested OPENROUTER provider live → generation+research ready → enabled. Reused active prompt versions (research starter, canonical_story, telegram_pack) with checksums. "Deterministic Fake" internal profile not referenced.
- Result: pass (later switched to a fake operator provider, see 10:40Z)
- Evidence: provider `4a847f92-cf4a-4174-9f81-e8f9c9b0c296`; brand profile `878b717a` (fa/rtl).

## 2026-08-23T21:32Z — Step 4 Workflow
- Did: created 4-node graph trigger→research→generate→save_drafts. Trigger output port is `article` (not `story`). Activation needs Idempotency-Key + expected_revision body.
- Result: pass
- Evidence: automation `f76e9a65-e7d5-455f-95f3-9fe9db67e6a0`, active.

## 2026-08-23T21:37Z — Step 5 Ingest + trigger
- Did: ingest once → 5/5 sources, 2026 items; stored articles into collection via operator PUT endpoint which fires `collection_article_added`.
- Blockers hit:
  1. `automation_controls.global_pause=true` silently swallowed trigger enqueues. Cleared via `PATCH /automation-control`.
  2. Month-old paused scheduler backlog (~1700 jobs, FIFO) starved automation jobs; scaled workers temporarily to drain.

## 2026-08-24T00:30Z — fix: dispatch_id KeyError masks research failures
- Did: content-pack continuations carry no `dispatch_id`; `_record_failure` crashed with KeyError while persisting the real error. Skip continuations without dispatch ids; regression test added.
- Result: fixed
- Changed: backend/app/research/handlers.py, backend/tests/research/test_handlers.py (334978b)

## 2026-08-24T08:05Z — fix: log unclassified research backend crashes
- Did: permanent-classified backend exceptions now emit traceback to worker log (was: generic research_failed with no diagnostics). Tests+lint pass.
- Result: fixed
- Changed: backend/app/research/handlers.py (0808d1a)

## 2026-08-24T09:20Z — root cause of instant research failures
- Did: traceback logging revealed `RuntimeError: Cannot send a request, as the client has been closed.` Worker's HttpClientOwner pools one shared httpx client, but `validate_availability*`/generation cleanup close the client they receive (fresh-client contract). First close poisoned all later jobs.
- Result: fixed — `_SharedClientLease` proxy in worker hands out the pooled client behind a no-op aclose; regression test added.
- Changed: backend/app/jobs/worker.py, backend/tests/test_job_worker.py (12655b3)

## 2026-08-24T09:45Z — operational notes
- Multi-replica `--scale worker-source-generation>1` breaks the API capability gate: replicas share component_id, every heartbeat registers as a restart, tripping restart_rate_high permanently. Single-replica is the supported mode; scale used only to drain the backlog.
- Stories bind permanently to their first research job idempotency key (story+provider+model+budgets); dead runs orphan stories until inputs change.

## 2026-08-24T10:40Z — live-model quality blocker; switch to deterministic fake chain
- Did: with OPENROUTER live (gpt-oss-20b), the full chain now runs mechanically but research reliably ends `waiting_for_review/openrouter_citation_invalid`: `_validated_finish` demands citations with exact `chars:start-end` locators plus the SHA-256 of the exact excerpt. A text LLM cannot compute excerpt hashes; input evidence carries only whole-document hashes, and character-count locators are unreliable for LLMs. Not fixable via config inputs alone (would need server-side citation resolution = code change out of Phase-1 scope).
- Result: blocked for live provider; per skill rules switched whole chain to a fake-protocol operator provider created through the public API ("E2E Fake", enabled).
- Evidence: failed run nodes show openrouter_citation_invalid; openrouter_loop.py:_validated_finish contract.

## 2026-08-24T10:55Z — Step 6 SUCCESSFUL end-to-end run
- Did: workflow v3 (fake provider) activated; re-fired article into collection B (`0303549e`). Run completed all four nodes.
- Result: pass
- Evidence: run `c69eaf87-8963-4199-a7fc-a0c79a5487bc` succeeded; ResearchRun `b39d5ed9` succeeded; content pack `32625f60`; PlatformVariantRevision `c1df679d-da1f-4691-bd0e-dcf1f7e1a2ee` approval_state=pending_review, validation_results=[platform_schema ok]; publish_jobs=0, publications=0 (review boundary held).

## 2026-08-24T10:58Z — Step 7 Quality verdict
- Provenance (1): pass — AutomationRun node artifacts link real ResearchRun/StoryRevision/content pack rows.
- Contract (4): pass — platform_schema validation ok; pending_review only; nothing published.
- Honesty (5): pass — failure states surface as waiting_for_review, never papered over.
- Groundedness (2): partial — fake chain is deterministic and evidence-shaped; live chain blocked by citation-hash contract above.
- Coherence (3): fail under fake provider — body is the literal placeholder "Deterministic Telegram rewrite" (language/tone cannot match brand profile fa/rtl).
- Verdict: pipeline goal reached (genuine AutomationRun-produced revision at the review boundary, zero hand-crafting), but the post is NOT publishable-quality. Publishing-grade output requires either live-provider citation assistance (code change) or a live model that can satisfy the exact-citation contract.
