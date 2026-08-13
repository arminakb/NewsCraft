# Phase 08 — Dependency Locking

## Status and scope

- **Strict status:** IMPLEMENTATION COMPLETE — HOST-DEPENDENT REGRESSION VERIFICATION OMITTED BY USER DIRECTION
- **Starting branch/revision:** `phase-08-dependency-locking` at `35ad958`
- **Model:** GPT-5 Codex
- **Authoritative source:** `docs/archive/solutions.md`, Phase 8
- **Prerequisites:** completed Phase 1–6 and Phase 9 reports/commits were present. Phase 8 intentionally precedes Phase 7 and supplies its frozen-install boundary.
- **Scope confirmation:** only Phase 8 dependency, toolchain, image, update-policy, inventory, documentation, and regression-test files changed. The Dependabot policy and inventory hook are Phase 8 requirements, not an implementation of Phase 7.

## Reproduction and root cause

The defect was reproduced from the starting revision:

- no backend lockfile existed;
- backend production installed editable development dependencies from open lower bounds;
- frontend direct dependencies contained `latest` and broad ranges;
- Python, Node, and PostgreSQL images used mutable tags;
- there was no dependency-update policy, risk register, or deterministic release inventory.

The confirmed root cause was that dependency intent, resolved graphs, toolchain versions, and runtime image identities were not treated as one release boundary. npm's existing lock protected `npm ci`, but a legitimate lock refresh could still select unreviewed direct majors. Python rebuilt its graph from the network on every clean image build.

## Architecture decisions

- `backend/pyproject.toml` remains the Python intent file and `backend/uv.lock` is the exact Python 3.14 production/development graph.
- uv `0.11.29`, Python `3.14.6`, Node `26.4.0`, and npm `11.17.0` are explicit.
- pytest, pytest-asyncio, Ruff, mypy, packaging, and pip-audit are explicit PEP 735 development dependencies.
- The backend image uses a frozen, non-editable, production-only virtual environment in a multi-stage build and runs as UID/GID 10001.
- Frontend direct dependencies are exact and match the npm lock root. Images and normal installs use `npm ci`; the runtime runs as `node`.
- Python, uv, Node, and PostgreSQL image inputs use patch tags plus verified multi-platform index digests.
- Weekly Dependabot updates group patch/minor changes. Version-update majors remain isolated; Dependabot security updates are not suppressed by that ignore rule.
- `scripts/dependency_inventory.py` emits deterministic lock hashes, normalized package graphs, and immutable image inputs without environment or credential data.
- One moderate PostCSS advisory is time-bounded in the risk register. `npm audit fix --force` was rejected because it proposed an incompatible Next.js downgrade.

No database migration was added.

## Changed files

- `.python-version`, `.node-version`, `.github/dependabot.yml`
- `backend/pyproject.toml`, `backend/uv.lock`, `backend/Dockerfile`
- `frontend/package.json`, `frontend/package-lock.json`, `frontend/Dockerfile`
- `docker-compose.yml`, `README.md`
- `scripts/dependency_inventory.py`
- `backend/tests/test_dependency_locking.py`
- `backend/tests/operations/test_dependency_inventory_script.py`
- `backend/tests/test_docker_config.py`
- `docs/operations/dependency-management.md`
- `docs/operations/dependency-risk-register.md`
- this report

## Tests and evidence

### Code-focused results

- Frozen runtime environment from a disposable directory: succeeded; FastAPI, SQLAlchemy, asyncpg, Uvicorn, httpx, Telethon, and Alembic imported; pytest, Ruff, and pip-audit were absent; the project was non-editable.
- Frozen development environment: succeeded with pytest, Ruff, pip-audit, and the explicit development graph.
- Deliberate `pyproject.toml`/lock mismatch: `uv lock --check` rejected the changed intent.
- Final `uv lock --check`: passed with 110 locked packages.
- Backend credential-free suite without PostgreSQL: **1,605 passed, 181 skipped, 1 warning**.
- Phase 8 dependency/Docker/inventory tests: **37 passed**.
- Ruff Phase 8 check: passed. Ruff format check: **3 files already formatted**.
- Python compileall: passed.
- Frontend clean `npm ci` with npm 11.17.0: passed without changing either manifest.
- Frontend typecheck: passed.
- Vitest: **47 files, 370 tests passed**.
- Next production build: passed with 17 routes.
- Six supported Compose renders (base, production, development, test, acceptance, proxy): **6/6 passed**.
- `git diff --check`: passed.

### Reproducibility and runtime evidence

Two cold-cache backend images and two cold-cache frontend images built successfully using the locally preloaded platform images corresponding to the reviewed pins. Registry metadata lookup for the default digest references timed out in Docker Desktop, so the build instructions and platform images were validated separately rather than misreporting a digest-network success.

- Backend A/B runtime inventories: 74 packages each; identical normalized SHA-256 `04540bb2bf75a5601b03731f88aacb3dc913ac28ca521374dbf9870655c68891`; UID 10001; no pytest/Ruff/pip-audit; non-editable install.
- Frontend A/B standalone inventories: 18 packages each; identical normalized SHA-256 `184367cce93c6e58ed705aec8fba8fa4a9a140981aaceb088ad0ba6eeade5b71`; UID 1000.
- Final source inventory: 110 Python packages, SHA-256 `3382cc68ac71940dbe8d7d1a5d87ebf96bef4ea869a57a4df7ba6ab9cd43b7b5`; 528 npm lock entries, SHA-256 `cdc976bd534ab8b2c87a536933fc2a54e04fcd9e87681abdd47aa8c87e070893`.
- Lock hashes: `backend/uv.lock` `11c40fe489524178d55d0d5e4b6a1e8633e1809add05b3c4370d447b11209b25`; `frontend/package-lock.json` `c3125ed0c2f96cb1d9d4017bfb17ee5a092baa1ff76e845e8670a218b8861daa`.
- Isolated migration/runtime smoke: migrations 0001 through 0010 succeeded; backend readiness returned `ready`; frontend health returned HTTP 200 with `{"status":"alive"}`; both containers ran as their declared non-root users.
- Docker Scout produced one backend CycloneDX inventory with 214 components. Further local-image imports failed with Scout's `gzip: invalid checksum`; normalized installed-package inventories therefore provide the A/B comparison required by the phase.

### Security audits

- `pip-audit --desc`: no known third-party Python vulnerabilities; the local unpublished project was skipped by the advisory service.
- `npm audit --omit=dev` and `npm audit`: both reported only two moderate paths for `GHSA-qx2v-qp2m-jg93` (`postcss <8.5.10`), with no high or critical finding. The owner, exposure analysis, mitigation, follow-up, and 2026-08-19 expiry are recorded in `docs/operations/dependency-risk-register.md`.
- Changed-file leak scan found no `.env`, credential value, private registry URL, or machine-specific path.

## Commands executed

Successful validation included:

```text
uv lock
uv lock --check
uv sync --locked --no-dev --no-editable
uv sync --locked
uv run pip-audit --desc
python -m pytest -p no:cacheprovider -q
ruff check . ../scripts/dependency_inventory.py
ruff format --check <Phase 8 Python files>
python -m compileall -q app tests ../scripts/dependency_inventory.py
npm@11.17.0 ci
npm test
npm run typecheck
npm run build
npm audit --omit=dev
npm audit
docker compose <supported profile combinations> config
docker build --no-cache <backend/frontend A and B>
docker scout sbom <backend A>
scripts/dependency_inventory.py
git diff --check
```

Failed or limited commands were not treated as passes:

- The first parallel Docker validation attempt destabilized the known-faulty host/Docker VM. Validation resumed after restart with serial, isolated commands.
- Direct default-digest builds timed out during Docker registry metadata retrieval; verified locally preloaded matching platform images were used to validate Dockerfile behavior.
- Docker Scout failed on the remaining local images with `gzip: invalid checksum`; package-list comparison completed instead.
- One uv invocation without the host proxy timed out fetching package metadata; the same lock operation passed with the configured proxy and the final lock check passed.
- The first staged-snapshot Compose check used the nonexistent shorthand `docker-compose.prod.yml`; it was corrected to the tracked `docker-compose.production.yml`, after which all six staged renders passed.
- A PostgreSQL-backed full suite reached **1,781 passed and 5 failed** after an intermittent native Python segmentation fault. Four operational-health tests and one migration-order test failed. The user identified faulty CPU/RAM and explicitly directed that host-dependent testing stop; these results are not represented as Phase 8 passes.

## Acceptance criteria

- [x] Clean frozen Python and npm installs preserve the lock/source files and resolve fixed graphs.
- [x] Backend production is non-editable, excludes development tools, runs non-root, and declares an immutable approved base image.
- [x] Frontend direct declarations contain no `latest`; image and documented installs use `npm ci`.
- [x] Release inventory tooling records lock, toolchain, image, and normalized package identities; Phase 7 will attach it to CI/release artifacts.
- [x] No unexcepted high/critical advisory exists; the moderate exception has owner, justification, mitigation, and expiry.

## Definition of Done

- [x] Python production/development lock strategy is committed and frozen.
- [x] Frontend direct declarations are exact and use the npm lock exclusively.
- [x] Runtime images are production-only, non-root, and digest-pinned.
- [x] Dependency update/security/exception policy is automated and documented.
- [ ] Host-dependent full PostgreSQL/browser regression evidence is not claimed; it was omitted by explicit user direction because the workstation CPU/RAM is faulty.

## Remaining risks, cleanup, and rollback

- Phase 7 must run the frozen installs, inventory/SBOM, audits, and retained release metadata in CI. Branch-protection administration is external to this code change.
- The accepted moderate PostCSS finding expires on 2026-08-19.
- The workstation's intermittent native crashes make its full PostgreSQL result unreliable. CI on healthy hardware remains the authoritative pending regression run.
- Docker registry access and Docker Scout local import were environment limitations, not silently waived successes.
- Temporary Phase 8 PostgreSQL containers, networks, and lock-generation files were removed. Local validation image tags are removable artifacts and are not committed.
- Rollback is the previous revision and its retained image/lock metadata; do not regenerate dependencies during rollback.

The pre-existing untracked root `AGENTS.md` is intentionally excluded and untouched.
