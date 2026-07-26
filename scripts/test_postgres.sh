#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_project="${NEWSCRAFT_TEST_PROJECT:-newscraft-postgres-tests}"
database_url="postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test"
started=false

cleanup() {
  if [[ "$started" == true && "${NEWSCRAFT_KEEP_TEST_DATABASE:-0}" != 1 ]]; then
    docker compose \
      --project-directory "$repo_root" \
      -p "$compose_project" \
      --profile test \
      down -v --remove-orphans
  fi
}
trap cleanup EXIT

if [[ ! -x "$repo_root/backend/.venv/bin/python" ]]; then
  echo "backend/.venv is unavailable; install the locked backend development dependencies first." >&2
  exit 2
fi

docker compose \
  --project-directory "$repo_root" \
  -p "$compose_project" \
  --profile test \
  up -d --wait postgres-test
started=true

export APP_ENV=test
export DATABASE_URL="$database_url"
export TEST_DATABASE_URL="$database_url"
export PYTHONPATH="$repo_root/backend"

cd "$repo_root/backend"
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/postgres \
  tests/integration \
  tests/stories/test_manual_intake_postgres.py \
  tests/stories/test_repository.py \
  tests/test_dispatch_sequence_migration_postgres.py \
  tests/test_runtime_heartbeat.py \
  "$@"
