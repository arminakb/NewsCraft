You are continuing the NewsCraft Production Hardening project on a different machine.

Implement **Phase 8 only: Dependency Locking and Reproducible Builds**.

There is no previous Phase 8 worktree available on this machine. Do not search for `/home/armin/Documents/newscraft-phase8` or depend on any uncommitted work from another computer.

Work from the main cloned `newscraft` repository.

## Repository setup

Before changing any files:

1. Locate the cloned `newscraft` repository.
2. Run:

```bash
pwd
git remote -v
git fetch --all --prune
git branch --show-current
git rev-parse HEAD
git status --short
git log --oneline -15
```

3. Ensure the local repository contains the latest pushed commits from the project's remote.
4. Start from the latest intended `main` revision.
5. The expected completed phases before Phase 8 are:

   * Phase 1
   * Phase 2
   * Phase 3
   * Phase 4
   * Phase 5
   * Phase 6
   * Phase 9
6. Verify those phase commits or reports exist. Do not reimplement them.
7. The working tree must be clean before Phase 8 starts.
8. Create and switch to:

```bash
git switch -c phase-08-dependency-locking
```

If that branch already exists locally or remotely, inspect it before deciding whether to resume or recreate it.

Do not work directly on `main`.

## Authoritative sources

Read these files if present:

* `solutions.md`
* `docs/implementation-reports/phase-01-telegram-route-response-boundary.md`
* `docs/implementation-reports/phase-02-worker-execution-boundary.md`
* `docs/implementation-reports/phase-03-restart-supervision.md`
* `docs/implementation-reports/phase-04-outbound-proxy-policy.md`
* `docs/implementation-reports/phase-05-safe-access-logging.md`
* `docs/implementation-reports/phase-06-credential-topology.md`
* Phase 9 implementation report
* current dependency and deployment documentation

`ACTIVE_TASK.md` may exist, but do not rely on it as the authoritative Phase 8 specification.

`ACTIVE_PHASE.md` may not exist. Its absence is not an error.

If `solutions.md` is absent, use the Phase 8 requirements in this prompt as the authoritative fallback and document that fact in the report.

## Important historical context

Phase 8 was previously implemented on another machine in an uncommitted worktree, but those files were not pushed and are unavailable here.

The previous implementation reported these results:

* complete `uv.lock`
* frozen backend runtime and development installations
* non-editable backend production packaging
* frontend `latest` declarations replaced with exact existing versions
* Python, uv, Node, and PostgreSQL images pinned by patch version and digest
* dependency policy and vulnerability-risk register
* automated dependency-locking tests
* backend suite: 1,783 passed
* clean frontend `npm ci`, typecheck, and production build
* identical dependency-inventory hashes across two clean image builds
* all six Compose variants rendered
* production images passed health checks

Treat this only as a target and historical reference. Independently inspect and implement Phase 8 on the current pushed revision.

Do not copy version numbers from this summary without verifying the current lockfiles, installed graph, Dockerfiles, and compatible image digests.

## Scope

Implement only:

* backend dependency locking
* frozen runtime and development installs
* runtime/development dependency separation
* non-editable backend production installation
* frontend direct dependency pinning
* frontend lockfile consistency
* deterministic Docker dependency installation
* reviewed base-image patch and digest pins
* dependency inventory checks
* reproducible-build evidence
* dependency update policy
* vulnerability-risk register
* Phase 8 tests
* Phase 8 implementation report

Do not implement:

* Phase 7 CI
* Phase 10 OpenAPI/type generation
* Playwright fixture repairs
* Phase 11 Story Inbox performance work
* unrelated dependency upgrades
* unrelated formatting cleanup
* application feature changes

## Initial inspection

Inspect:

* `backend/pyproject.toml`
* all backend lock, requirements, or constraints files
* backend Dockerfile
* backend development/test setup
* `frontend/package.json`
* `frontend/package-lock.json`
* frontend Dockerfile
* Compose files and image declarations
* README and installation documentation
* scripts that install Python or Node dependencies
* `.python-version`, `.node-version`, `.nvmrc`, or tool-version files if present
* the currently installed Python, uv, Node, and npm versions

Record the current versions of at least:

* Python
* uv
* FastAPI
* Starlette
* Pydantic
* SQLAlchemy
* asyncpg
* Uvicorn
* httpx
* Telethon
* Alembic
* pytest
* Ruff
* Node
* npm
* Next.js
* React
* TypeScript
* Vitest
* Playwright
* Tailwind
* TanStack Query
* PostgreSQL

Confirm:

* whether a backend lock currently exists
* whether it is complete and current
* whether production installs resolve dynamically
* whether production installs development dependencies
* whether production installation is editable
* which frontend declarations use `latest`, `*`, or overly broad ranges
* whether `npm ci` currently succeeds without modifying the lockfile
* which Docker images are tag-only rather than digest-pinned

## Implementation requirements

### 1. Backend locking

Use one authoritative Python dependency workflow.

Preferred structure:

* `backend/pyproject.toml` remains the human-edited dependency-intent source
* one committed `uv.lock` is the generated lock source
* runtime and development/test groups are explicit
* frozen installation is mandatory

Requirements:

* lock the complete runtime graph
* lock the complete development/test graph
* preserve required platform markers
* use integrity information supported by the selected locking tool
* support the project's intended Python version
* avoid unrelated dependency upgrades
* document every unavoidable version change

A clean frozen install must fail if `pyproject.toml` and the lock disagree.

### 2. Runtime versus development separation

Backend production images must exclude development-only packages, including where applicable:

* pytest
* Ruff
* coverage tooling
* test plugins
* development utilities

Production installation must be non-editable.

Development and test environments may install the explicit development group.

Verify all actual runtime imports remain present in the runtime group.

### 3. Frontend dependency declarations

Replace direct dependency declarations using:

* `latest`
* `*`
* unstable or unjustifiably broad ranges

Use exact reviewed versions matching the currently tested `package-lock.json` graph unless a documented compatibility correction is required.

Do not perform arbitrary major upgrades.

Verify:

```bash
npm ci
```

succeeds from a clean checkout and does not change:

* `package.json`
* `package-lock.json`

Keep runtime packages in `dependencies` and test/build tooling in `devDependencies`.

### 4. Toolchain policy

Make these explicit and consistent:

* Python version
* uv version
* Node version
* npm version
* PostgreSQL version
* approved lock-generation commands
* approved clean-install commands

Use repository tool-version files or package-manager metadata where appropriate.

### 5. Docker installation

Update Dockerfiles so that:

* lock and intent files are copied before source where appropriate
* dependency installation uses frozen mode
* production backend install is non-editable
* backend production excludes development dependencies
* frontend uses `npm ci`
* mismatched lock and intent files cause build failure
* dependency installation does not silently resolve newer packages
* build caching cannot hide lock inconsistencies

### 6. Base-image pinning

Inventory all production-critical base and Compose images.

Pin reviewed patch versions and immutable digests where practical, including:

* Python
* uv helper image if used
* Node
* PostgreSQL
* other build/runtime helper images already used by the project

Keep readable tags alongside digests where supported.

Do not introduce unrelated operating-system migrations.

Before committing a digest, verify it exists and matches the intended architecture.

### 7. Reproducibility evidence

Build backend and frontend production images twice using clean dependency installation.

Compare at least:

* Python dependency inventory hash
* Node dependency inventory hash
* relevant SBOM or package-list output
* application build success
* health/import smoke behavior

Do not claim byte-for-byte image reproducibility unless it was directly proven.

Document expected nondeterminism such as timestamps and image metadata.

### 8. Dependency policy

Create or update documentation describing:

1. edit dependency intent
2. regenerate lock with the approved tool version
3. inspect the dependency diff
4. run boundary-sensitive tests
5. run relevant full suites
6. run vulnerability audits
7. build production images
8. commit intent and lock together

Dependency updates must be isolated, reviewed changes.

Do not enable unreviewed automatic major upgrades.

### 9. Vulnerability review

Run appropriate audits for the locked graphs, including:

* `pip-audit` or an equivalent supported Python audit
* npm audit or OSV-based frontend audit
* image/SBOM scan if available

Classify each relevant finding:

* fixed
* not affected
* temporarily accepted
* blocked by compatibility
* deferred with follow-up

For accepted risks, record:

* package and advisory
* severity
* exploitability in NewsCraft
* rationale
* owner/follow-up
* review or expiry date

Do not force broad upgrades merely to make the audit appear green.

## Automated tests

Add or update tests verifying:

### Backend

* backend lock exists
* lock matches dependency intent
* frozen runtime installation succeeds
* frozen development installation succeeds
* deliberately inconsistent intent/lock fails
* production package inventory excludes development tools
* runtime imports succeed
* production installation is non-editable

### Frontend

* no direct dependency uses `latest` or wildcard declarations
* clean `npm ci` succeeds
* clean `npm ci` leaves no repository drift
* runtime and development dependency classification is valid
* typecheck and production build pass

### Docker and Compose

* backend production image builds from frozen runtime dependencies
* frontend production image builds using the lock
* production images import/start correctly
* all supported Compose variants render
* intended image pins and digests are present

### Completed-phase regressions

Run focused tests protecting completed phases, especially:

* SQLAlchemy transaction behavior
* worker crash recovery
* restart and health behavior
* proxy policy
* Uvicorn redaction
* credential capability state
* operational diagnostics

## Known downstream failures

The previous machine observed:

* one Story Inbox Vitest timeout, likely owned by Phase 11
* stale mocked Playwright fixtures, owned by Phase 10
* moderate PostCSS advisory paths requiring temporary acceptance

Reproduce and verify ownership.

Do not:

* increase the Story Inbox timeout
* optimize Story Inbox
* fix Playwright route mocks
* generate OpenAPI frontend types
* start Phase 10
* remove tests to achieve a green number

Document confirmed downstream failures separately.

## Validation

Perform validation from clean temporary environments.

### Backend

Run:

* frozen clean runtime installation
* frozen clean development installation
* full backend suite
* Ruff lint
* targeted Ruff formatting checks
* Python compilation
* production import check
* dependency inventory export
* Python vulnerability audit

### Frontend

Run:

* remove or isolate existing `node_modules`
* clean `npm ci`
* verify no lockfile drift
* full typecheck
* full Vitest
* production build
* frontend dependency inventory
* frontend vulnerability audit

### Docker and Compose

Build:

* backend production image twice
* frontend production image twice

Render:

* base Compose
* production Compose
* development Compose
* test Compose
* acceptance Compose
* proxy Compose

Verify both production images start or pass their health checks.

### General

Run:

```bash
git diff --check
```

Also verify:

* no credential values were added
* no local absolute paths were added to committed documentation
* no cache, virtual environment, build output, or temporary file is included
* no unrelated feature was changed

Clean up Phase 8-only:

* virtual environments
* temporary dependency caches
* temporary containers
* temporary images
* temporary networks
* generated files not intended for Git

Do not remove shared developer resources that were not created by Phase 8.

## Acceptance criteria

Do not mark Phase 8 complete unless directly verified:

* one authoritative backend dependency-intent source exists
* a complete backend lock exists
* frozen backend runtime installation succeeds
* frozen backend development installation succeeds
* production backend excludes development tools
* production backend installation is non-editable
* frontend direct dependencies contain no `latest` or wildcard declarations
* `npm ci` succeeds with zero repository drift
* backend and frontend production images build from frozen graphs
* Python, uv, Node, npm, and image policies are documented
* dependency update policy is documented
* vulnerability audits are executed and findings classified
* completed phases remain green
* no unrelated phase is implemented
* temporary Phase 8 resources are cleaned up

A confirmed Phase 10 fixture failure or Phase 11 performance timeout does not by itself make Phase 8 incomplete, but it must be documented accurately.

## Final report

Create:

`docs/implementation-reports/phase-08-dependency-locking.md`

The report must include:

* starting branch and revision
* confirmed original reproducibility problems
* selected locking tool and rationale
* lock artifacts created
* exact toolchain versions
* dependency declaration changes
* production/development separation
* Docker and image changes
* exact commands
* exact test results
* clean-install evidence
* image-build evidence
* dependency-inventory hashes
* vulnerability findings and classifications
* downstream Phase 10/11 issues
* acceptance checklist
* remaining risks
* unverified items
* confirmation that no other phase was implemented
* strict final status

## Commit

After all directly applicable Phase 8 criteria pass:

1. Review every changed and untracked file.
2. Stage only Phase 8 implementation, tests, locks, Docker changes, policies, risk register, and report.
3. Exclude:

   * task-control files
   * credentials
   * `.env`
   * local artifacts
   * caches
   * build output
   * unrelated source changes
4. Run:

```bash
git diff --cached --name-status
git diff --cached --check
```

5. Create one commit:

```text
build: lock dependencies and make production installs reproducible
```

6. Do not push unless explicitly requested.

## Final response

Report:

* Phase 8 commit hash
* included files
* exact tool and image versions
* test and build results
* reproducibility hashes
* security audit classification
* remaining known downstream failures
* remaining dirty files
* final Git status
* confirmation that no Phase 7, Phase 10, Phase 11, or other phase was implemented

Stop after completing and committing Phase 8.
