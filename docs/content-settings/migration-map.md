# Content Settings Migration Map

Status: architecture lock
Date: 2026-07-22

## Sequencing

1. Phase 1 adds principals/scopes, protected mutations, encrypted-secret storage, and security audit events. Existing secret references continue working temporarily.
2. Phase 2 adds generic `llm_providers`, migrates OpenRouter metadata, and imports credentials only through explicit secure input.
3. Phase 3 adds proxy profiles, normalized Telegram destinations, encrypted bot/proxy credentials, health stages, and dependency-safe lifecycle APIs.
4. Phase 4 adds paired Codex connections and replaces bootstrap Codex credentials.
5. Phase 5 adds MCP facade.
6. Phase 6 changes UI after backend lifecycle validation.
7. Phase 7 makes prompt/default ownership explicit and removes unsafe seed behavior.

Each expansion uses additive schema first, dual-read compatibility second, caller migration third, then legacy removal in a later deploy.

## Existing to target mapping

| Existing | Target | Migration rule |
|---|---|---|
| `ai_provider_profiles` OpenRouter row | `llm_providers` `openai_compatible` | preserve UUID when possible; copy name/model/base URL/settings/enabled; mark operator-managed |
| provider `secret_ref` | encrypted secret FK | never resolve/import automatically; require explicit operator secret entry, then verify before cutover |
| Codex provider row | Codex Gateway connection | do not migrate as generic provider; disable compatibility row after gateway validation |
| `destinations.target_ref` | canonical target and target type | normalize; collisions enter operator-review table and do not auto-merge |
| destination `secret_ref` | encrypted bot-token FK | explicit secure import and successful `getMe`/target/admin check before cutover |
| destination `settings.allow_auto_publish` | Automation route policy | preserve false; true becomes review-required migration warning, never silent route permission |
| destination without proxy | nullable `proxy_profile_id` | maps to Direct |
| prompt templates/versions | ownership-aware prompt governance | retain IDs/checksums/history; mark existing non-seed versions operator-managed |

## Phase 1 database migration

Add `encrypted_secrets` and `security_audit_events`. Do not alter current provider/destination foreign keys yet. This makes rollback safe and lets Phases 2–3 migrate one resource at a time.

Master key must exist before any encrypted write. Missing key never blocks application startup or safe reads, but secret create/rotate/decrypt fails closed. Production deployment validation must confirm active key/version before enabling credential-write routes.

## Provider migration

Create target rows disabled when no encrypted secret exists. Validate generic protocol and capability checks before switching worker resolution. Dual-read order during migration is explicit target row first, legacy profile only when migration state says `legacy`; never silently fall back after target activation.

Foreign-key consumers are migrated transactionally or through compatibility views/adapters while retaining historical IDs. Deletion remains blocked by Automation routes, research/generation runs, and jobs.

## Telegram migration

Backfill canonical targets in a shadow column. Report normalization collisions for operator choice. Never choose a winner by creation time. After collision resolution, add unique constraint and switch reads.

Existing destinations remain Direct. Bot-token import is explicit. A destination becomes enabled in target model only after route-specific health check succeeds. Publishing never falls back to legacy secret reference after encrypted-secret cutover.

`allow_auto_publish=true` does not migrate into destination permissions. Related Automation routes retain their explicit publishing policy; unmatched destination flags become warnings requiring operator acknowledgement.

## Prompt and seed migration

Add ownership/seed metadata without rewriting content or active selection. Derive operator-managed status for any row changed from known seed checksum. Startup creates only absent defaults. Repair never changes active flags or operator content.

## Rollback

- Schema rollback drops only unused additive Phase 1 tables after confirming no encrypted secrets or required audit retention.
- During dual-read, rollback switches callers to legacy rows without deleting target data.
- After encrypted-secret cutover, rollback requires retained old application version plus matching key versions; plaintext/export rollback is forbidden.
- Provider/destination target rows remain disabled until verified, so rollback never routes work to an unverified credential.
- Prompt rollback restores code behavior only if it does not overwrite operator activation; destructive seed rollback is prohibited.

## Verification gates

- migration dry run reports counts, normalization collisions, missing credentials, and dependencies;
- no response, log, job, trace, or audit row contains canary secrets;
- restart preserves operator values and active prompt version;
- old and new worker paths never both perform one material side effect;
- downgrade rehearsed against snapshot with retained key versions;
- legacy columns removed only after one full rollback window and provenance audit.
