You are continuing the NewsCraft Production Hardening project.

Use **GPT-5.5 xhigh**.

Your task is to **resume, verify, finalize, and commit Phase 8 only: Dependency Locking and Reproducible Builds**.

Do not implement Phase 10, Phase 7 CI, Phase 11, or any other phase.

## Existing Phase 8 work

The existing Phase 8 worktree is expected at:

`/home/armin/Documents/newscraft-phase8`

Expected branch:

`phase-08-dependency-locking`

Phase 8 was already implemented in that worktree, but no commit was created because the previous session ended.

Known reported results:

* Complete `uv.lock` added.
* Frozen backend runtime and development installs implemented.
* Backend production packaging changed to non-editable installation.
* Frontend `latest` declarations replaced with exact existing versions.
* Python, uv, Node, and PostgreSQL images pinned by patch version and digest.
* Dependency policy, risk register, locking tests, and Phase 8 report added.
* Backend: `1,783 passed`.
* Ruff, compilation, imports, and `pip-audit` passed.
* Frontend clean `npm ci`, typecheck, and production build passed.
* Two clean builds per image produced identical dependency-inventory hashes.
* Six Compose variants rendered.
* Both production images passed health checks.
* Temporary Phase 8 resources were reportedly cleaned up.

Previously reported remaining items:

* Phase 8 changes were uncommitted.
* Full Vitest was `369/370` because of one Story Inbox timeout assigned to Phase 11.
* Mocked Playwright failures were caused by stale Phase 10 fixtures.
* Two moderate PostCSS advisory paths were temporarily accepted and documented.

Do not blindly trust this summary. Verify the repository state and evidence yourself.

## Mandatory preflight

Before editing anything:

1. Enter the expected Phase 8 worktree.
2. Run:

   * `pwd`
   * `git branch --show-current`
   * `git rev-parse HEAD`
   * `git status --short`
   * `git diff --stat`
3. Confirm that the branch is `phase-08-dependency-locking`.
4. Confirm that the dirty files correspond to Phase 8.
5. Read:

   * `solutions.md`
   * `ACTIVE_TASK.md` if present
   * `docs/implementation-reports/phase-08-dependency-locking.md`
   * dependency policy and risk-register documents
6. Do not require `ACTIVE_PHASE.md`; it may not exist.
7. If the worktree path, branch, or changes do not match the expected Phase 8 state, stop and report the exact mismatch before changing files.

## Primary objective

Produce a self-contained Phase 8 commit that makes dependency installation and production builds reproducible.

The resulting commit must not depend on files outside the Phase 8 worktree or on unstaged local modifications.

## Phase 8 scope

Phase 8 includes only:

* backend dependency intent and locking
* frontend dependency declaration normalization
* frontend lockfile consistency
* runtime versus development dependency separation
* non-editable backend production installation
* frozen Docker dependency installation
* reviewed base-image version and digest pins
* dependency inventory and reproducibility checks
* dependency-update policy
* vulnerability-risk register
* Phase 8 tests and documentation
* `docs/implementation-reports/phase-08-dependency-locking.md`

Do not fix:

* stale Playwright fixtures
* frontend/backend contract drift
* Story Inbox performance
* CI workflows
* unrelated formatting backlog
* unrelated application behavior

## Verification of implementation

Inspect and verify that the current changes satisfy the following.

### Backend locking

* `pyproject.toml` is the human-edited dependency-intent source.
* One complete committed lock artifact exists, preferably `uv.lock`.
* Runtime and development/test dependency groups are explicit.
* Frozen runtime installation succeeds.
* Frozen development installation succeeds.
* Production installation is non-editable.
* Production installation excludes test and lint tools.
* Required runtime imports work from the production environment.
* The supported Python and uv versions are explicit.

### Frontend locking

* No direct dependency uses:

  * `latest`
  * `*`
  * an unjustifiably broad unstable range
* Exact versions correspond to the tested lockfile unless a documented change was required.
* `npm ci` succeeds from a clean checkout.
* `npm ci` does not modify `package-lock.json`.
* Runtime and development dependencies are correctly classified.
* Node and npm version policy is explicit.

### Docker and Compose

* Backend Docker builds use frozen locked installation.
* Backend production image does not install development dependencies.
* Frontend Docker builds use `npm ci`.
* Lock and intent files are copied before source where appropriate for cache correctness.
* Builds fail when intent and lock disagree.
* Python, Node, PostgreSQL, and relevant helper images use reviewed version pins and digests.
* Base, production, development, test, acceptance, and proxy Compose variants render successfully.

### Documentation and security

* Dependency update procedure is documented.
* Security findings are classified rather than hidden.
* The PostCSS moderate advisory paths include:

  * package/advisory
  * severity
  * project exploitability
  * temporary acceptance rationale
  * owner or follow-up action
  * review or expiry date
* No credential, local environment value, cache, or build output is included.

## Known non-Phase-8 failures

Re-run enough tests to verify ownership.

The following may remain outside Phase 8 only if evidence confirms they are unrelated:

### Story Inbox Vitest timeout

Expected ownership:

`Phase 11 — Inbox performance`

Do not increase the timeout or optimize Story Inbox as part of Phase 8.

### Mocked Playwright failures

Expected ownership:

`Phase 10 — Contract drift and stale fixtures`

Do not modify Playwright fixtures, OpenAPI generation, frontend wire types, or route mocks as part of Phase 8.

Document these as unrelated downstream blockers, not Phase 8 implementation failures.

## Clean-snapshot validation

Before committing, validate the staged Phase 8 snapshot independently from unstaged files.

Use a detached worktree, exported index, or equivalent clean-snapshot method.

At minimum run:

### Backend

* frozen clean runtime installation
* frozen clean development installation
* backend production import
* dependency inventory generation
* Phase 8 locking-policy tests
* full backend test suite
* Ruff lint
* targeted Ruff formatting checks
* Python compilation
* `pip-audit`

### Frontend

* remove or isolate existing `node_modules`
* clean `npm ci`
* verify zero package-lock drift
* TypeScript typecheck
* production build
* full Vitest to confirm the exact known timeout ownership
* frontend dependency inventory
* npm or OSV audit

### Docker and Compose

* clean backend production image build
* clean frontend production image build
* backend image import/start smoke
* frontend image health check
* render:

  * base Compose
  * production Compose
  * development Compose
  * test Compose
  * acceptance Compose
  * proxy Compose

### Reproducibility

Build each production image twice with clean dependency installation where feasible.

Compare dependency-inventory hashes.

Do not claim byte-for-byte image reproducibility unless demonstrated.

### General

Run:

* `git diff --check`
* `git diff --cached --check`
* secret and absolute-path sweep
* generated-file and temporary-artifact sweep

## Report portability

Review:

`docs/implementation-reports/phase-08-dependency-locking.md`

Remove or normalize non-portable paths such as:

* `/home/armin/...`
* random `/tmp/...` paths

Commands may be documented using repository-relative paths or placeholders.

Historical local evidence may be retained only when clearly labeled and when the report remains useful from another checkout.

Update the strict status based on verified evidence.

A suitable status is:

`IMPLEMENTATION COMPLETE — DOWNSTREAM PHASE 10/11 REGRESSION GATES REMAIN`

Do not mark a known Phase 10 or Phase 11 issue as a Phase 8 failure.

## Staging and commit

After verification:

1. Classify every changed and untracked file as:

   * Phase 8 implementation
   * Phase 8 tests/documentation
   * unrelated
   * generated/temporary
2. Stage only Phase 8 files.
3. Review:

   * `git diff --cached --name-status`
   * `git diff --cached --stat`
   * `git diff --cached --check`
4. Ensure no cache, virtual environment, build output, credential, temporary audit artifact, or task-control file is staged.
5. Create one commit:

`build: lock dependencies and make production installs reproducible`

Do not amend or rewrite earlier completed-phase commits.

## After the commit

Create a clean Phase 10 branch or worktree based exactly on the Phase 8 commit, but do not implement Phase 10.

Preferred branch name:

`phase-10-contract-drift`

Report the exact command used and the resulting path/branch.

## Final response

Report:

* verified starting branch and commit
* Phase 8 commit hash
* every file included in the commit
* lock artifacts
* exact Python, uv, Node, npm, and image versions
* clean runtime/dev installation results
* backend test result
* frontend typecheck/build/Vitest results
* Docker and Compose results
* reproducibility inventory hashes
* audit findings and temporary acceptances
* files intentionally excluded
* remaining dirty files
* Phase 10 branch/worktree created
* confirmation that no Phase 10 or other phase was implemented
* strict Phase 8 status

Stop after committing Phase 8 and preparing the clean Phase 10 branch/worktree.
