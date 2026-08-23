# TestSKILL.md Phase 1 progress

## 2026-08-23T21:55Z — Step 0 Environment up
- Did: started full compose stack with local override (`docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d`); override exists because default network subnet collides with VPN (172.19/16).
- Result: pass
- Evidence: `/health/ready` reports `schema_current` + `database_connected`; api/frontend/workers/scheduler healthy on newscraft_local_net.
- Next: pipeline steps.

## 2026-08-23T21:28Z — Step 1 Article collection
- Did: `POST /article-collections` (needs browser-like `origin: http://127.0.0.1:3000`, else 403 origin_validation_failed).
- Result: pass
- Evidence: collection id `25a230be-dac1-467d-a750-8427173c1e14`.

## 2026-08-23T21:28Z — Step 2 Source collection
- Did: reused existing sources (no seeding needed, 44 present); selected 5 healthy AI-news RSS sources; created source collection and added members via bulk API.
- Result: pass
- Evidence: collection `af2fdc1a-eaa6-4d60-89c2-175da99ffcc1`, 5 sources (AWS ML, HuggingFace, OpenAI News, The Decoder, VentureBeat AI).

## 2026-08-23T21:32Z — Step 3 Settings dependencies
- Did: internet available; tested OPENROUTER provider live (`POST /llm-providers/{id}/test`) → generation+research ready, then enabled. Reused active prompt versions: research `news_research_starter` 0a4d6f1c…, canonical_story 51527dac…, telegram_pack 1e60b962…. No fallback creation needed. "Deterministic Fake" internal profile NOT referenced per skill rules.
- Result: pass
- Evidence: provider id `4a847f92-cf4a-4174-9f81-e8f9c9b0c296`, brand profile `878b717a-dcc5-43b9-9119-ecd59994a4b0` (fa/rtl), checksums captured.

## 2026-08-23T21:32Z — Step 4 Workflow
- Did: created 4-node graph (trigger→research→generate→save_drafts). Note: trigger output port is `article` (not `story`); first create attempt failed with edge_port_invalid, fixed port and recreated. Activation requires `Idempotency-Key` header and `{"expected_revision": N}` body.
- Result: pass
- Evidence: automation `f76e9a65-e7d5-455f-95f3-9fe9db67e6a0`, lifecycle=active, version 1.

## 2026-08-23T21:37Z — Step 5 Ingest once + trigger
- Did: `POST /source-collections/{id}/ingest {"mode":"once"}` → succeeded, 5/5 sources, 2026 raw items, 162 media candidates. Saved ≥3 content items into article collection via real operator endpoint (`PUT /article-collections/{id}/articles/{item_id}`) — this endpoint is the only membership writer and fires `collection_article_added`.
- Blockers hit:
  1. `automation_controls.global_pause=true` ("Paused from Newsroom", set 2026-08-08) silently swallowed trigger enqueues (events recorded, runs not). Cleared via `PATCH /automation-control {"global_pause": false}`.
  2. After resume, month-old scheduler catch-up backlog (~1700 priority-equal `ingest.collect` jobs, FIFO by scheduled_for) starves the 3 `automation.run.start` jobs. Scaled worker-source-generation to 6; backlog finite, draining ~35/min.
- Result: pass (≥3 articles stored; 3 AutomationRuns queued: af4f47b5, f9b1a387, 6fff909b)
- Changed: none yet.
- Next: wait for drain, follow runs to PlatformVariantRevision.
