# Backup and restore

NewsCraft backups use the `newscraft-backup-v2` contract. A final backup is an authenticated
age-encrypted archive containing only a PostgreSQL custom dump, media archive, export archive,
and strict manifest. It never includes `.env`, Compose renders, application logs, provider
credentials, Telegram credentials, or the decryption identity.

The manifest records a backup ID, UTC consistency window, Git revision, Alembic revisions,
PostgreSQL server and dump-client majors, container image IDs, an independent logical database
data hash, per-payload checksums, and deterministic media/export inventory root hashes. Legacy
v1 plaintext archives remain readable for recovery, but the backup command no longer publishes
new plaintext archives.

## Keys, schedule, and SLO

Generate and escrow an age identity outside the repository and application services:

```bash
install -d -m 0700 "$HOME/.config/newscraft-backup"
age-keygen -o "$HOME/.config/newscraft-backup/identity.txt"
age-keygen -y "$HOME/.config/newscraft-backup/identity.txt" \
  > "$HOME/.config/newscraft-backup/recipient.txt"
chmod 0600 "$HOME/.config/newscraft-backup/identity.txt" \
  "$HOME/.config/newscraft-backup/recipient.txt"
```

Keep the identity in approved offline/backup-key escrow and test recovery after every rotation.
The operational baseline is nightly backup, RPO <=24 hours, RTO <=2 hours, retention of 7 daily,
5 weekly, and 12 monthly generations, and a full disposable restore drill at least quarterly.

## Quiesced encrypted backup

Check health, source size, backup filesystem space, and temporary filesystem space first:

```bash
docker compose ps
df -h . ./backups "${TMPDIR:-/tmp}" 2>/dev/null || df -h . "${TMPDIR:-/tmp}"
docker compose exec -T postgres psql -U newscraft -d newscraft -Atqc \
  "SELECT pg_size_pretty(pg_database_size('newscraft'));"
docker compose --profile operations run --rm --no-deps backup \
  sh -ceu 'du -sh /data/media /data/exports'
```

Create the backup:

```bash
python scripts/backup_restore.py backup \
  --output-dir ./backups \
  --recipient-file "$HOME/.config/newscraft-backup/recipient.txt" \
  --identity-file "$HOME/.config/newscraft-backup/identity.txt" \
  --staging-dir /run/newscraft-backup
```

`--staging-dir` must already exist with mode 0700 on tmpfs or an approved encrypted filesystem
and must have room for the plaintext dump plus both file archives. The tool records which writer
services are running, stops only those writers, rejects capture
while any other database client session remains, and captures all three stores through the
credential-minimal `backup` Compose service. That service has read-only media/export mounts,
the matching PostgreSQL client, pinned age package, and no OpenRouter or Telegram authority.
The tool verifies plaintext internally, encrypts it, decrypts and verifies the ciphertext, then
resumes exactly the writer services that were running before atomically publishing one mode-0600
`.newscraft-backup.tar.gz.age` file. Private plaintext exists only in a mode-0700 staging tree and
is removed on every exit. A failed capture publishes nothing and attempts to resume prior writers.

Verify the encrypted copy before and after approved off-host transfer:

```bash
python scripts/backup_restore.py verify \
  ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz.age \
  --identity-file "$HOME/.config/newscraft-backup/identity.txt"
```

## Safe retention

Preview retention first. Invalid/unreadable archives are reported and never deleted; the newest
verified backup is always protected.

```bash
python scripts/backup_restore.py prune \
  --output-dir ./backups \
  --identity-file "$HOME/.config/newscraft-backup/identity.txt"

python scripts/backup_restore.py prune \
  --output-dir ./backups \
  --identity-file "$HOME/.config/newscraft-backup/identity.txt" \
  --apply
```

Retention verification is local. Apply the same generation policy in approved off-host storage,
verify before and after transfer, and alert on a failed/missed backup, newest verified backup older
than 24 hours, or insufficient capacity.

For a single-host deployment, install the reviewed units from `operations/systemd/`, create the
dedicated `newscraft-backup` OS account, grant only the Docker/project access required by this
workflow, and provision `/etc/newscraft-backup` and `/var/backups/newscraft` as mode-0700 paths.
The timer runs backup, retention, and freshness/capacity status sequentially and gives the full
operation a two-hour deadline. Connect failed-unit state to the deployment's normal paging path:

```bash
sudo install -m 0644 operations/systemd/newscraft-backup.service \
  operations/systemd/newscraft-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now newscraft-backup.timer
systemctl list-timers newscraft-backup.timer
```

## Disposable restore drill

Do not test recovery against the primary project. Prepare three independent mode-0600 files:
the age identity, a unique canary value that exists only in runtime secret storage, and a report
HMAC key of at least 32 random bytes. Then run:

```bash
python scripts/restore_drill.py \
  --archive ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz.age \
  --identity-file "$HOME/.config/newscraft-backup/identity.txt" \
  --secret-canary-file "$HOME/.config/newscraft-backup/canary.txt" \
  --report-signing-key-file "$HOME/.config/newscraft-backup/report-hmac.key" \
  --project-name newscraft-restore-drill-YYYYMMDD-a \
  --api-port 18000 \
  --output-dir reports/restore-drills \
  --cleanup
```

The project name must match the strict `newscraft-restore-drill-*` allowlist. The override removes
the primary database/frontend ports, binds only the selected loopback API port, clears live
authority, and forces fake-provider/dry-run behavior. Project-scoped volumes are new. Before any
`down -v`, the tool inspects every container's `com.docker.compose.project` label and refuses
cleanup on a mismatch.

The drill rejects incompatible PostgreSQL server/restore-client majors before destructive work,
restores DB/media/exports, migrates forward, compares the logical DB data hash and exact file
inventories, rejects unvalidated constraints, scans restored DB/media/exports/manifest for the
count-only secret canary, checks readiness, and runs the credential-free smoke. It writes a
mode-0600 JSON report plus HMAC-SHA256 signature containing RPO/RTO, archive hash, backup ID,
integrity evidence, smoke result, and cleanup result. Preserve both files in the approved audit
store. If a drill fails, omit `--cleanup` while investigating; never manually use `down -v` until
the disposable project label has been independently confirmed.

## Emergency in-place restore

> **Warning:** this drops and recreates the current database and replaces every media/export
> file. Prefer restore into new stores followed by controlled cutover. Take a fresh verified
> backup and retain the old stores read-only through the rollback window.

```bash
python scripts/backup_restore.py restore \
  ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz.age \
  --identity-file "$HOME/.config/newscraft-backup/identity.txt" \
  --confirm-replace
```

Verification, age authentication, manifest checks, PostgreSQL major compatibility, and
`pg_restore --list` all run before writer shutdown or replacement. The restore then stops the API,
both workers, scheduler, and frontend; recreates/restores the DB; replaces media and exports; runs
Alembic; and restarts the five services. On any partial failure it contains runtime services and
prints the exact recovery command. Do not run that command until the database and both volumes are
known consistent; normally re-run the same verified restore. Never delete the prior stores or the
source archive until readiness, smoke, integrity, RPO/RTO, report signature, and rollback review
are signed complete.
