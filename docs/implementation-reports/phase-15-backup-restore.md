# Phase 15 — Backup and Restore Proof

## Status and scope

- **Strict status:** IMPLEMENTATION COMPLETE — HEALTHY-HARDWARE DISPOSABLE RESTORE EXECUTION PENDING
- **Starting revision:** `5f057ce` on `phase-15-backup-restore`
- **Authoritative source:** `solutions.md`, Phase 15
- **Prerequisites:** Phase 3 service control, Phase 6 credential separation, Phase 7 scheduled evidence retention, Phase 8 pinned images, and Phase 9 readiness/smoke are present.

The prior tool verified a plaintext archive but captured PostgreSQL, media, and exports sequentially while writers remained active. It had no encryption, generation retention, compatible-client enforcement, safe new-project restore orchestrator, automatic integrity/canary/smoke proof, or retained signed drill result.

## Implemented recovery contract

- Backup archives use strict `newscraft-backup-v2`; legacy v1 plaintext archives remain readable for emergency recovery.
- Backup discovers the currently running writer set, stops only those writers, verifies that no other database client session remains, captures all stores while quiesced, and resumes exactly the prior writer set on both success and failure.
- A dedicated `operations/backup.Dockerfile` uses the same digest-pinned PostgreSQL 18.3 image and exact Debian age 1.1.1 package. Its Compose service has only database connectivity plus read-only media/export mounts and receives no OpenRouter or Telegram authority.
- The v2 manifest records backup ID, Git SHA, Alembic current/head, image IDs, server/dump-client versions and majors, exact quiescence interval, payload hashes/sizes, deterministic per-file volume inventories, and per-table row counts/content hashes with a canonical root SHA-256.
- Plaintext is permitted only under an explicit existing mode-0700 staging directory on tmpfs or approved encrypted storage. The tool verifies plaintext internally, encrypts with age, decrypts/authenticates and re-verifies, removes staging, resumes writers, then atomically publishes only a mode-0600 `.age` file. Destination publication safely crosses filesystems without exposing plaintext.
- Verification and restore accept age identities only from private files. Wrong/missing identity, corrupt ciphertext/tool failure, unsafe tar paths, links, duplicate/unexpected members, checksum/inventory mismatch, malformed metadata, and non-custom dumps fail before replacement.
- Restore enforces PostgreSQL target server and restore-client major compatibility before `pg_restore --list` and before runtime shutdown. Legacy archives enforce their recorded server major.
- Retention verifies every encrypted candidate, preserves the newest valid backup, keeps the union of 7 daily/5 weekly/12 monthly generations, reports invalid files without deleting them, defaults to dry-run, and rechecks each digest immediately before explicit deletion.
- Status monitoring fails closed when no verified encrypted backup exists, the newest exceeds the configured RPO age, or free capacity is below threshold.
- Reviewed systemd service/timer templates run nightly backup, retention, and status sequentially under a dedicated account, private umask/runtime staging, and a two-hour deadline.

## Disposable drill and evidence

`scripts/restore_drill.py` accepts only strict `newscraft-restore-drill-*` project names. Its Compose override creates project-scoped stores, removes primary host ports, binds only an explicit loopback API port, clears all live provider/Telegram authority, and forces fake-provider/dry-run operation.

The drill:

1. validates project name, encrypted archive, key/canary/signing-key permissions, free space, and port availability;
2. decrypts and verifies before creating the disposable project;
3. restores and migrates the new database/media/export stores;
4. compares exact database table counts/content hashes and media/export inventory roots;
5. rejects unvalidated PostgreSQL constraints;
6. performs a count-only secret-canary scan over logical database output, media, exports, and manifest without logging the canary;
7. requires readiness and the credential-free fake-provider/dry-run smoke;
8. records archive/backup identity, RPO, RTO, hashes/inventories, integrity, canary, readiness, smoke, and cleanup state in a mode-0600 JSON report with HMAC-SHA256 signature.

Cleanup inspects every Compose container and volume project label before any `down -v`. A separate cleanup command applies the same rule after an interrupted drill. The primary project/stores are never stopped or removed by the drill.

Nightly CI now builds the minimal backup image, creates ephemeral age/canary/report keys, starts a credential-free source stack, creates a real encrypted quiesced archive, checks freshness, restores into a disposable project, runs the proof, signs the report, and retains only non-secret test/report evidence for 30 days.

## Changed artifacts

- `scripts/backup_restore.py`
- `scripts/restore_drill.py`
- `scripts/cleanup_restore_drill.py`
- `operations/backup.Dockerfile`
- `operations/systemd/newscraft-backup.service`
- `operations/systemd/newscraft-backup.timer`
- `docker-compose.yml` and supported overlays
- `docker-compose.restore-drill.yml`
- `.github/workflows/nightly.yml`, `.github/dependabot.yml`
- `scripts/dependency_inventory.py`, `.gitignore`, `README.md`
- `docs/operations/backup-and-restore.md`
- backup, drill, Compose, CI, dependency, and inventory policy tests
- this report

## Local evidence and limitations

- Python compilation passed for all three recovery scripts.
- Ruff lint and format checks passed for every changed Python source/test.
- Focused fake-runner, archive, encryption-boundary, quiescence, compatibility, retention, freshness, staging cleanup, drill-containment, HMAC, canary, CI, dependency, inventory, and non-Docker Compose policy checks: **72 passed in 0.74 seconds**.
- `git diff --check` passes.

No Docker image build, live PostgreSQL archive, destructive restore, readiness call, or smoke was run locally. The user identified faulty CPU/RAM and explicitly directed that host-dependent execution stop. Those claims remain pending on healthy scheduled/manual CI; no simulated unit result is represented as an end-to-end recovery pass.

## Acceptance and Definition of Done

- [x] Cross-store capture is bounded by verified writer quiescence and versioned in the manifest.
- [x] New backups are authenticated/encrypted, internally round-trip verified, atomically published, retained, and freshness/capacity monitored.
- [x] The backup runtime has matching pinned PostgreSQL tooling, exact age tooling, read-only file mounts, and no external-provider authority.
- [x] Restore compatibility, corruption, wrong-key, unsafe-member, partial-publication, resume/containment, and last-good retention paths have deterministic coverage.
- [x] Restore targets a strict new disposable project and cleanup is container/volume-label contained.
- [x] DB content/count hashes, exact file inventories, constraints, secret canary, readiness, credential-free smoke, RPO/RTO, signed evidence, and rollback preservation are automated.
- [x] Baseline nightly/7 daily/5 weekly/12 monthly/quarterly drill policy and operator workflow are documented.
- [ ] A healthy runner must complete the real encrypted backup/restore nightly job and retain its signed report.
- [ ] Production storage/key escrow, off-host transfer, paging integration, and first approved quarterly report require operator infrastructure authorization.

## Rollback and residual risk

- Do not revert to live sequential capture or plaintext publication. If v2 activation fails, preserve old v1 read support while fixing the v2 producer.
- The generic database content inventory hashes all public-table row JSON hashes and may lengthen downtime on very large databases; measure it in the first healthy drill and keep the integrity proof rather than silently dropping it.
- The bundled age package is exact-pinned to Debian bookworm's 1.1.1 build and the image base is digest-pinned. Updates require dependency review, encrypted compatibility proof, and key-escrow recovery testing.
- The in-place command remains explicitly destructive for local emergencies. Normal recovery uses new stores/project and retains old stores until signed cutover review.
- A failed drill report intentionally stores only the exception type, not raw exception text, to avoid leaking a key, canary, archive path authority, or restored content.

The pre-existing untracked root `AGENTS.md` remains excluded and untouched. No Phase 13 or Phase 14 behavior was implemented.
