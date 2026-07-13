# Backup and restore

This runbook covers the local Compose stack. A NewsCraft backup contains only a PostgreSQL
custom-format dump plus the exact `/data/media` and `/data/exports` volume contents. It does
not contain `.env`, credentials, rendered Compose environments, or logs.

The archive schema is `newscraft-backup-v1`. Its manifest records the UTC creation time, Git
SHA, current and head Alembic revisions, PostgreSQL version, filenames, byte counts, and
SHA-256 checksums. Verification also rejects unsafe tar paths, links, duplicates, unexpected
or missing files, malformed manifests, and unsafe paths or links inside the media and export
tarballs.

## Before a backup

Run all commands from the repository root. Confirm the stack is healthy and check the source
data size against free space on the filesystem that will hold `./backups`:

```bash
docker compose ps
df -h . ./backups "${TMPDIR:-/tmp}" 2>/dev/null || df -h . "${TMPDIR:-/tmp}"
docker compose exec -T postgres psql -U newscraft -d newscraft -Atqc \
  "SELECT pg_size_pretty(pg_database_size('newscraft'));"
docker compose exec -T api du -sh /data/media /data/exports
```

Leave enough free space for the database dump, both compressed volume archives, the final
archive, and temporary verification copies. Standalone `verify` and `restore` stage their
verified members under `${TMPDIR:-/tmp}`, so that filesystem must also have room for the dump
and both volume archives. A backup failure publishes no final archive.

## Create and verify

```bash
python scripts/backup_restore.py backup --output-dir ./backups
python scripts/backup_restore.py verify \
  ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz
```

Backup uses these live service boundaries:

- `docker compose exec -T postgres pg_dump -U newscraft -d newscraft --format=custom`
- `docker compose exec -T api tar -C /data/media -czf - .`
- `docker compose exec -T api tar -C /data/exports -czf - .`

The tool stages data in a private `0700` directory, verifies the complete archive, and then
publishes the final `0600` file atomically. Copy an archive off-host only through an approved
encrypted storage path and verify it again after copying.

## Destructive restore

> **Warning:** restore drops and recreates the current `newscraft` database, then replaces
> every file under `/data/media` and `/data/exports`. It is not a merge and cannot be undone
> without another verified backup.

Take a fresh backup of the current state first. Then run:

```bash
python scripts/backup_restore.py verify \
  ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz
python scripts/backup_restore.py restore \
  ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz \
  --confirm-replace
```

The restore verifies the archive and asks `pg_restore --list` to validate the database dump
before changing anything. It then stops exactly `api`,
`worker-source-generation`, `worker-publishing`, `scheduler`, and `frontend`. PostgreSQL stays
up while the database is recreated and restored. Only after `pg_restore --exit-on-error`
succeeds does the tool replace the media and export contents, run `alembic upgrade head`, and
restart those five services. Expect the UI, API, workers, and scheduler to be unavailable for
the duration.

If any destructive step fails, the tool retries the aggregate stop and then tries each runtime
service individually if necessary. When it confirms containment, it reports that all five
runtime services remain stopped and prints this recovery command:

```bash
docker compose start api worker-source-generation worker-publishing scheduler frontend
```

Do not run it until the failure has been understood and the database and both volumes are in
a consistent state. Re-running restore with the same verified archive is the normal recovery
path.

If the tool instead reports that runtime service stop state could not be confirmed, inspect and
stop the services explicitly before any recovery work:

```bash
docker compose ps
docker compose stop api worker-source-generation worker-publishing scheduler frontend
docker compose ps
```

Do not run the recovery/start command while any of those services has an unconfirmed state.

## Post-restore proof

Confirm services and migration state:

```bash
docker compose ps
docker compose run --rm --no-deps api alembic current
```

Record durable row counts for comparison with the pre-backup drill record:

```bash
docker compose exec -T postgres psql -U newscraft -d newscraft <<'SQL'
SELECT 'stories' AS object, count(*) FROM stories
UNION ALL SELECT 'story_evidence_snapshots', count(*) FROM story_evidence_snapshots
UNION ALL SELECT 'story_evidence_links', count(*) FROM story_evidence_links
UNION ALL SELECT 'story_revisions', count(*) FROM story_revisions
UNION ALL SELECT 'platform_variant_revisions', count(*) FROM platform_variant_revisions
UNION ALL SELECT 'automation_routes', count(*) FROM automation_routes
UNION ALL SELECT 'publications', count(*) FROM publications
UNION ALL SELECT 'media_assets', count(*) FROM media_assets
ORDER BY object;
SQL
docker compose run --rm --no-deps api sh -ceu \
  'find /data/media -type f | wc -l; find /data/exports -type f | wc -l; du -sh /data/media /data/exports'
```

Compare these results with the counts and file totals recorded immediately before backup.
Inspect a representative story, evidence record, revision, route, publication, media object,
and export through the application before declaring the restore usable.

## Quarterly disposable-project drill

Run a restore drill at least quarterly during a planned interruption. The separate Compose
project name creates separate database, media, export, and staging volumes. The primary
project is brought down without `-v`, so its volumes remain intact; never use `down -v` until
the disposable project name is active and verified.

```bash
ARCHIVE="$PWD/backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz"
python scripts/backup_restore.py verify "$ARCHIVE"

# Record the post-restore proof queries above, then free the bound local ports.
docker compose down

export COMPOSE_PROJECT_NAME="newscraft-restore-drill-$(date -u +%Y%m%d)"
docker compose up -d --build postgres api worker-source-generation \
  worker-publishing scheduler frontend
docker compose ps
python scripts/backup_restore.py restore "$ARCHIVE" --confirm-replace

# Run every post-restore proof query above and record the result in the drill log.
docker compose ps

# This -v applies only to the disposable project while COMPOSE_PROJECT_NAME is set.
docker compose down -v
unset COMPOSE_PROJECT_NAME

# Return to the preserved primary volumes.
docker compose up -d postgres api worker-source-generation \
  worker-publishing scheduler frontend
docker compose ps
```

If the drill fails before disposable cleanup, keep `COMPOSE_PROJECT_NAME` set while diagnosing
it. Confirm `docker compose ls` and `docker volume ls` show the drill project before any
`down -v` command. Keep the archive, command output, counts, file totals, duration, and failure
notes as the quarterly drill record.
