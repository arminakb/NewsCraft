# Phase 07 — Missing CI Workflow

## Status and scope

- **Strict status:** IMPLEMENTATION COMPLETE — FIRST REMOTE RUN AND BRANCH PROTECTION PENDING
- **Starting revision:** `42eb369` on `phase-07-ci`
- **Model:** GPT-5 Codex
- **Authoritative source:** `solutions.md`, Phase 7
- **Prerequisite:** Phase 8 commit `42eb369` supplies frozen Python/npm graphs, immutable image inputs, audits, and dependency inventory.

The starting revision had `.github/dependabot.yml` but no workflow. A merge could therefore bypass every backend, database, migration, frontend, contract, Compose, security, and browser check. The root cause was missing executable repository policy, not a missing local test command.

## Architecture decisions

`.github/workflows/ci.yml` provides nine independently diagnosable blocking jobs and one final `release-gate`:

1. `backend-static`: frozen development install, compileall, Ruff lint/format, and an explicit mypy baseline.
2. `backend-unit`: credential-free non-PostgreSQL suite with coverage and JUnit.
3. `backend-postgres`: migrated `_test` database plus PostgreSQL and process-crash suites.
4. `migrations`: one-head assertion, empty-database upgrade/current/check, and supported migration regression.
5. `frontend`: clean route type generation, typecheck, Vitest JUnit, and production build.
6. `contracts`: backend API and frontend wire-mapping suites. Phase 10 will strengthen this with canonical generated artifacts.
7. `compose-and-images`: six topology renders, immutable-input tests, production image builds, two CycloneDX SBOMs, two high/critical Trivy gates, and dependency inventory retention.
8. `security`: Python/npm audit policy, credential-boundary tests, and full-history Gitleaks.
9. `browser-mocked`: Chromium Playwright with traces and HTML evidence. Phase 10 owns any remaining mock drift.

`release-gate` runs even after a dependency fails and requires every result to be `success`. No job uses `continue-on-error`. Concurrency cancels superseded branch runs. Pull-request permissions are read-only, live OpenRouter/Telegram secrets are explicitly blank where relevant, and no workflow references repository live-secret expressions.

`.github/workflows/nightly.yml` adds scheduled/manual credential-free real-stack smoke, worker restart evidence, backup/restore contract tests, and the current story-inbox budget test. Phase 11 and Phase 15 may strengthen their owned drills without putting live credentials in PR CI.

The workflow retains JUnit, coverage, Playwright, topology, SBOM, scan, and inventory evidence for 30 days. `docs/operations/continuous-integration.md` defines failure ownership and the external branch-protection settings.

## Supporting changes

- Added explicit `pytest-cov` to the locked development group.
- Added a reviewed incremental mypy baseline over seven safety/operations files. A whole-repository discovery run found 301 pre-existing errors in 55 files; those were not mass-suppressed or silently called green. The gate starts with seven clean files and can expand through reviewed fixes.
- Two type-only corrections preserve runtime behavior: `_BypassRule` narrows a network value before membership testing, and `JobExecution.from_job` documents/casts the ORM enum value already validated in `__post_init__`.
- Stabilized `frontend/next-env.d.ts` to the clean `next typegen` production route-types path. This removes dependence on stale `.next/dev` output.

No migration or public API behavior changed.

## Changed files

- `.github/workflows/ci.yml`
- `.github/workflows/nightly.yml`
- `backend/pyproject.toml`, `backend/uv.lock`
- `backend/app/core/outbound_proxy.py`
- `backend/app/jobs/types.py`
- `backend/tests/test_ci_workflows.py`
- `frontend/next-env.d.ts`
- `docs/operations/continuous-integration.md`
- this report

## Validation evidence

- `actionlint` v1.7.7: both workflow files passed.
- Referenced action tags were resolved with `git ls-remote`; the Trivy action is pinned to the verified v0.36.0 commit.
- CI policy tests: **4 passed**.
- Focused workflow/type/runtime regression set: **42 passed**.
- Frontend contract sample: **2 files, 29 tests passed**.
- Vitest JUnit command proof: **1 file, 28 tests passed**, with a nonempty JUnit artifact.
- Clean `next typegen` plus TypeScript: passed after deleting stale `.next`; the generated `next-env.d.ts` transition is committed.
- Mypy baseline: **success, 7 source files**.
- Ruff focused check: passed; focused format check: **7 files already formatted**.
- `uv lock --check`: passed with 112 packages.
- YAML parse/policy tests, `git diff --check`, and credential-expression checks passed.

Commands included:

```text
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/*.yml
uv lock
uv lock --check
uv sync --locked
python -m mypy
python -m pytest -p no:cacheprovider -q <focused Phase 7 suites>
ruff check <Phase 7 Python files>
ruff format --check <Phase 7 Python files>
npm test -- --run tests/api-client.test.ts tests/backend-proxy-route.test.ts
npm test -- --run tests/api-client.test.ts --reporter=default --reporter=junit ...
rm -rf frontend/.next && npm exec next typegen && npm run typecheck
git ls-remote <referenced action repositories and tags>
git diff --check
```

Failed/limited commands were not counted as passes:

- The first actionlint rerun was launched from `backend/`, so its root-relative glob found no workflow; rerunning from the repository root passed.
- One Ruff format check was launched from the repository root and therefore did not discover `backend/pyproject.toml`; rerunning from `backend/`, matching CI, passed all 7 selected files.
- The first staged-export Ruff invocation also ran from the outer repository root and misclassified the backend first-party import boundary; rerunning inside the exported `backend/` directory passed. The exported-index tests and actionlint had already passed.
- The first typecheck read a malformed stale `.next/dev/types/validator.ts`; the workflow's designed clean-generation sequence removed `.next`, regenerated types, and passed. It also exposed the required tracked `next-env.d.ts` stabilization.
- One uv lock refresh timed out at the package index; the retry completed and the final lock check passed.
- A guessed Trivy `0.33.1` reference omitted the repository's `v` prefix. Tag inspection caught it before commit; CI now pins the verified v0.36.0 commit.
- No GitHub Actions run was dispatched because this branch is local and the user did not authorize a push. No deliberate remote-failure matrix or cache warm/cold timing was claimed.
- Host-service-heavy suites and local production image builds were intentionally not rerun after the user identified faulty CPU/RAM and directed code-focused work.

## Acceptance and Definition of Done

- [x] Required jobs cover static, unit, PostgreSQL/integration, migrations, frontend, contracts, Compose/images/SBOM, security, and browser mocks.
- [x] `release-gate` fails unless every blocking job succeeds.
- [x] Frozen installs and 30-day sanitized artifact retention are encoded.
- [x] PR CI receives no live provider or Telegram credential.
- [x] Scheduled/manual real-stack, restart, restore-contract, and inbox-budget drills exist.
- [x] Production image jobs inspect runtime contents after build: the backend
  imports the application with no pytest/Ruff installation, and the frontend
  contains the standalone server plus generated static assets.
- [ ] A pushed test branch must prove remote execution, deliberate category failures, cold/warm cache equivalence, and median duration.
- [ ] GitHub branch protection must require `Release gate`, an approval, current branch, and resolved conversations.

## Risks, cleanup, and rollback

- Until Phase 10 lands, the intentionally blocking contract/browser jobs may expose the already documented mock drift. They must not be weakened; Phase 10 owns the correction.
- The initial mypy boundary is intentionally small and explicit. Expanding it is preferable to adding blanket ignores.
- GitHub-hosted runner behavior, action artifact production, and branch settings remain unverified external state.
- Temporary mypy environments, uv caches/binaries, generated `.next`, and JUnit proof files were removed.
- Rollback is a single revert of the Phase 7 commit. Do not leave a partially weakened `release-gate` in place.

The pre-existing untracked root `AGENTS.md` remains intentionally excluded and untouched. No other phase was implemented.
