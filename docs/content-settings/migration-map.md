# Content Settings Migration Map

Status: completed migration reference
Date: 2026-07-26

This file records how the original Content Settings data maps to the current
runtime. It is not an active phase plan.

## Current state

- `encrypted_secrets` and `security_audit_events` own credential storage and
  mutation evidence. A master key is required for encrypted writes; missing key
  material fails secret operations closed without blocking safe reads.
- `llm_providers` is the operator-managed provider model. OpenAI-compatible
  credentials are entered explicitly, tested before enablement, and never
  imported from environment-variable references.
- Provider create/update maintains a same-ID `ai_provider_profiles`
  compatibility projection for the existing automation, research, generation,
  and job foreign keys. This is write-through compatibility, not a startup
  importer or a dual-execution path.
- Application startup no longer scans or promotes legacy provider rows.
- Codex remains outside `llm_providers` and uses the paired Codex Gateway.
- Telegram destinations use canonical targets, encrypted bot credentials,
  optional proxy profiles, staged health checks, and dependency-aware deletion.
- Automatic publishing is route policy. A destination flag never grants it
  implicitly.
- Prompt defaults are inserted only when absent. Operator content, active
  versions, and ownership are not rewritten at startup.

## Historical-to-current mapping

| Historical field | Current owner | Completed rule |
|---|---|---|
| `ai_provider_profiles` OpenRouter row | `llm_providers` `openai_compatible` | recreate through the operator lifecycle; no automatic startup migration |
| provider `secret_ref` | encrypted secret FK | enter explicitly, verify, then enable |
| Codex provider row | Codex Gateway connection | pair through the gateway; never treat as a generic provider |
| `destinations.target_ref` | canonical target and target type | normalize and require operator resolution for collisions |
| destination `secret_ref` | encrypted bot-token FK | enter explicitly and pass bot, target, and administrator checks |
| destination auto-publish flag | automation route policy | review-required unless the route explicitly confirms automatic publishing |
| destination without proxy | nullable `proxy_profile_id` | direct transport |
| prompt templates/versions | ownership-aware prompt governance | preserve IDs, checksums, history, content, and active selection |

## Operational rules

- Deletion remains blocked by live automation, research, generation, and job
  dependencies.
- Workers resolve current provider and destination records only; old and new
  paths never perform the same material side effect.
- Restart must preserve operator values and the active prompt version.
- No response, log, job, trace, or audit row may contain secret canaries.
- Rollback after encrypted-secret cutover requires the matching key versions;
  plaintext or exported-secret rollback is forbidden.
