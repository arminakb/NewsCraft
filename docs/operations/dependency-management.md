# Dependency and reproducible-build policy

NewsCraft treats dependency intent, lockfiles, tool versions, and base-image digests as one reviewed release boundary.

## Pinned toolchain

- Python `3.14.6` from `.python-version`.
- uv `0.11.29`, enforced by `backend/pyproject.toml`.
- Node.js `26.4.0` from `.node-version`.
- npm `11.17.0`, supplied by the pinned Node image and enforced by `frontend/package.json`.
- PostgreSQL `18.4-trixie`, pinned to its multi-platform OCI digest in `docker-compose.yml` to preserve the collation provider used by existing volumes.
- Python, uv, and Node container inputs use readable patch tags plus immutable multi-platform digests.

The committed digest identifies the reviewed multi-platform image index. A release must record the resolved platform manifest digest as well as the index digest.

## Updating Python dependencies

1. Edit dependency intent in `backend/pyproject.toml`.
2. Install exactly uv `0.11.29` and run `uv lock --upgrade-package <name>` for an isolated update, or `uv lock` after an intentional intent-only change.
3. Review the complete `pyproject.toml` and `uv.lock` diff. Major upgrades require a dedicated change.
4. Run `uv lock --check`, then create disposable runtime and development environments with `uv sync --locked --no-dev --no-editable` and `uv sync --locked`.
5. Run the full backend suite plus the SQLAlchemy, Uvicorn, httpx proxy, Pydantic/OpenAPI, and Telethon boundary suites affected by the update.
6. Run `uv run pip-audit --desc` and update `docs/operations/dependency-risk-register.md` for every unresolved finding.
7. Build the production backend image twice without dependency cache and compare the normalized installed-package inventory and CycloneDX inventory hashes.
8. Commit `pyproject.toml` and `uv.lock` together with the tests and risk review.

Production uses the default runtime dependencies only. The PEP 735 `dev` group owns pytest, Ruff, mypy, pip-audit, test helper libraries, and future development-only tools. Production installation is frozen and non-editable.

## Updating frontend dependencies

1. Change one direct exact version, or one tightly related package family, in `frontend/package.json`.
2. Use Node `26.4.0` and npm `11.17.0`; run `npm install --package-lock-only` once to update `package-lock.json`.
3. Review the direct and transitive lock diff. Never use `latest`, `*`, or an unreviewed broad range.
4. In a clean directory run `npm ci`, typecheck, Vitest, the production build, and relevant Playwright suites.
5. Run `npm audit --omit=dev` and `npm audit`; classify unresolved findings in the risk register.
6. Build the production frontend image twice and compare normalized `npm ls --all --json` or SBOM package inventories.
7. Commit `package.json` and `package-lock.json` together.

## Base-image and security updates

Dependabot opens weekly uv, npm, and Docker updates. Patch/minor dependency updates may be grouped; majors stay separate and require an explicit compatibility plan. High or critical security updates are reviewed immediately and are never suppressed by the major-version policy.

Before changing an image digest, verify the readable patch tag, multi-platform index digest, required `linux/amd64` and `linux/arm64` manifests, upstream release notes, full image build, non-root user, health behavior, and dependency inventory. Retain the previous built image and release metadata until the rollback window closes.

An accepted advisory must record package, advisory, severity, affected surface, exploitability, mitigation, owner, follow-up, and expiry. Expired exceptions fail the release review. Do not use force-upgrade commands to hide incompatible advisories.

## Release evidence

Each release retains:

- Git revision and both lockfile hashes;
- Python, uv, Node, npm, and PostgreSQL versions;
- base-image index and resolved platform digests;
- normalized Python and Node dependency inventory hashes;
- CycloneDX or equivalent SBOMs for backend and frontend images;
- vulnerability reports and the reviewed risk-register revision;
- health/import smoke results and immutable pushed image digests.

Timestamp-bearing image metadata can differ between builds. NewsCraft claims reproducible dependency graphs only when normalized inventories match; byte-for-byte image reproducibility requires a separate direct proof.
