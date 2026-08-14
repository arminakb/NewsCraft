# Handoff: heavy verification pass (deferred 2026-08-14)

The owner's machine could not run the heavy suites during the refactor
finish, so functional work was verified with the LIGHT gates only. This
file is a complete, copy-pasteable prompt for a future session (or a
beefier machine) to close the loop. Give it to the orchestrator session
verbatim, or run the commands yourself in order.

## Context

- Branch: `agent/finish-refactor-plan` (pushed). NO merge without the
  owner's explicit approval.
- All 372 verified refactor findings were fixed/dispositioned across
  Opus chain waves and sol sweeps; light gates were green at every
  integration point.
- LIGHT gates already green at handoff (re-run to confirm nothing
  drifted): backend `pytest` (2011 passed), `mypy` (0), `ruff` (0),
  frontend vitest (599/599), `tsc --noEmit`, strict unused-code tsc.
- Model routing directive (2026-08-14, owner): delegated fixes run on
  codex `gpt-5.6-sol` (effort high, max for hardest scopes; reviews max
  only) via `.orchestrator/scripts/codex-{fix,review}.sh`. No Claude
  subagents.

## Environment notes

- Python 3.14.6; `uv` on the machine is 0.12.1 but pyproject pins
  0.11.29 — bypass uv with `backend/.venv/bin/python -m pytest|mypy|ruff`.
- `npm ci` only, never `npm install`.
- Next dev/test runs regenerate `frontend/next-env.d.ts` to the dev
  variant; `git checkout -- frontend/next-env.d.ts` before committing —
  a CI-guard test asserts the committed variant.
- Docker required for the postgres/acceptance suites (disposable DBs —
  never point tests at a real database).

## The heavy battery (run in order, exit-code gated, no pipes)

1. `scripts/test_postgres.sh`
   - EXPECTED: green. Three tests were failing earlier and their causes
     were fixed WITHOUT a confirming heavy run (fixed blind, need
     verification):
     - `tests/postgres/test_ingestion_identity_concurrency.py::test_repeated_edited_source_item_updates_without_duplicate`
       → fixed by `_preserve_more_complete_content` now preserving only
       on explicit `source_excerpt`/`unavailable` re-parses
       (backend/app/ingestion/repository.py).
     - `tests/postgres/test_articles_api.py::test_articles_handle_legacy_source_and_missing_optional_fields`
       → expectations updated for the icon fields (2 assertion sites).
     - `tests/postgres/test_article_collections_api.py::test_collection_article_trigger_starts_one_durable_run_and_preserves_article_output`
       → expectations updated for principal-derived `actor_id`
       (`test_harness:pytest`), trigger `event_type`, and the enriched
       top-level `collection` object.
   - If any OTHER test fails: it is likely a seam between merged
     verticals; diagnose before patching, and prefer fixing code over
     weakening tests.
2. `scripts/test_acceptance.sh` — was green at last full run.
3. `backend/.venv/bin/python scripts/quality_baseline.py --check`
   - At handoff the remaining debt was complexity/LOC only (wave-3 sol
     fixers were closing it — check the ledger tail for the final
     numbers). Ruff/mypy/TS-unused must be 0.
4. `cd frontend && npm run test && npm run typecheck && npm run build`
5. `cd frontend && PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:e2e`
   - Frontend behavior changed this run (proxy header sanitization, dead
     module removal, framer-motion → native SVG animation), so e2e is
     REQUIRED before merge.

## After the battery is green

6. Cold review (owner directive: sol at MAX):
   `.orchestrator/scripts/codex-review.sh 8d5129a` (BASE_SHA of the whole
   refactor). Triage every finding per the guardrails (auth/privacy/data
   integrity/migrations/contracts/concurrency/idempotency ≥ P1
   regardless of the reviewer's label); verify each finding independently
   before accepting; fix cycle cap 2 via `codex-fix.sh`.
7. Update `.orchestrator/state.md` + ledger with evidence; report to the
   owner. Merge only on the owner's explicit approval of the exact PR.

## Known open items (not blockers, recorded for completeness)

- Deferred cross-vertical findings: `.orchestrator/runs/refactor-2026-08-13/verify/wave2b-*-deferred.json`
  and `wave2c-deferred.json` — sweep them when convenient (single fixer,
  no concurrent siblings, generous ownership).
- Sol sweep COULD_NOT_FIX_SAFELY items (all ownership-scoped, see
  `.orchestrator/runs/sol-*/fix.json`): canonical-hashing move through
  telegram automation, shared redaction helpers placement in app/core.
- The flaky-under-load `frontend/tests/manual-publishing-checklist.test.tsx`
  was fixed; if any test flakes under parallel load again, fix with the
  waitFor pattern of commit 3155f34, never by retry loops.
