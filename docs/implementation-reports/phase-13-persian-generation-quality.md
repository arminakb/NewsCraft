# Phase 13 — Persian generation quality

## Outcome

The repository-side qualification system is implemented. Provider failures now
produce safe stage diagnostics, provider model/settings identity is part of job
idempotency and is revalidated at the network boundary, retry behavior remains
on the selected model, and a protected 36-story x2 Persian evaluation campaign
plus signed threshold scorer is available.

The funded external campaign itself was not run on this host. Production
qualification therefore remains pending until an approved model/profile,
isolated evaluation database, editor review, and campaign budget are supplied.
The profile must not be marked qualified until the signed report passes.

## Implemented controls

- OpenRouter failures distinguish HTTP status, response JSON, choices, message,
  content type/JSON, JSON Schema, Telegram schema, usage, finish reason,
  resolved model, and post-redaction validation stages.
- Persisted diagnostics contain only allowlisted stage/type/path metadata,
  response byte count/SHA-256, bounded request ID, and safe requested model.
  Raw response values and credentials are not persisted.
- An optional invalid-output quarantine is disabled by default. When explicitly
  enabled, it enforces a strict byte ceiling, encrypts response bytes directly
  from memory with an `age` recipient (no plaintext file), uses a worker-only
  recipient mount, audits hash/artifact metadata, and prunes at a maximum
  seven-day TTL. Quarantine failures never replace the safe primary diagnostic.
- HTTP 402/configuration failures remain permanent; malformed output remains
  needs-review; transport, 408, 429, and 5xx failures retry the same model.
  `Retry-After` is honored up to five minutes, otherwise bounded exponential
  backoff with deterministic jitter is used.
- Provider configuration identity covers profile ID, provider type, resolved
  model, validated safe settings, pricing/budgets, generation policy, and prompt
  compatibility. Secret values and secret references are excluded.
- Content-pack and regeneration payloads/idempotency include the immutable
  provider revision/checksum. Workers refresh and resolve the profile again
  immediately before calling the provider and reject drift permanently.
- The qualified policy schema pins output-token, attempt, elapsed-time, cost,
  retry-class, and no-automatic-fallback settings.
- OpenRouter profiles without explicit pricing and a `qualified` generation
  policy are rejected for editorial generation; fake/Codex test and local paths
  remain available under their existing capability controls.
- `corpus-v1.json` contains 36 immutable synthetic Persian fixtures with exact
  RSS/Telegram, length, category, calibration/held-out, conflict,
  insufficient-evidence, mixed-script, and language-conflict strata.
- The internal evaluation identity creates 72 independent packs and cannot be
  supplied through public API request schemas.
- The runner seeds only its explicitly marked isolated database, enqueues four
  platforms with research disabled, waits for terminal jobs, and records 360
  baseline stages plus attempts, retry reasons, tokens, cost, model, and latency.
- The scorer requires two distinct blinded reviews per variant, mandatory
  adjudication for differences over one point, claim support/citation labels,
  language/encoding/title/promotion decisions, all acceptance thresholds,
  canonical input hashes, a report hash, and HMAC-SHA256 signature.
- A protected `workflow_dispatch` campaign uses the locked Python environment,
  a file-scoped worker secret, an isolated database marker, concurrency fencing,
  an explicit profile, and a preapproved positive budget.

## Verification

Lightweight verification was used because the workstation is known to be
hardware-unstable:

```text
ruff check (affected generation, validation, and tests): passed
pytest test_openrouter_provider.py test_provider_profile_resolver.py
       test_persian_generation_evaluation.py test_invalid_output_quarantine.py
       test_credential_capabilities.py test_generation_settings_api.py
       generation/test_editorial_service.py test_dependency_locking.py:
       123 passed in 1.66s
corpus validation: 36 stories / 72 independent executions / 360 baseline calls
git diff --check: passed
```

No live provider request, funded campaign, editor review, Docker stack, or broad
CPU/RAM-intensive suite was run locally.

## External acceptance still required

1. Create a funded OpenRouter profile with explicit pricing and a qualified
   generation policy; retain its configuration checksum.
2. Configure the protected `persian-generation-evaluation` environment with an
   isolated migrated database, required reviewer approval, provider secret, and
   approved campaign ceiling.
3. Run the manual workflow and verify 72 packs, 288 variants, and 360 baseline
   provider stages are complete.
4. Collect two blinded native-Persian reviews for every variant and adjudicate
   every greater-than-one-point disagreement.
5. Run the signed scorer. Enable the profile only when `passed` is true and all
   corpus, prompt, provider, run, review, report, and signature hashes are kept.

## Rollback

Disable the failing profile for new work and return affected jobs to review.
Do not silently switch models. Restore the last independently qualified
profile/prompt pair and require a new 12-story canary before resuming.
