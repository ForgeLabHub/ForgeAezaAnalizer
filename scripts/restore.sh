#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
ROOT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd -P)
cd "$ROOT_DIR"

if [ $# -lt 1 ]; then
  echo "usage: $0 <backup_dir> [--yes]" >&2
  exit 2
fi

BACKUP_DIR="$1"
CONFIRM="${2:-}"

ANALYTICS_DUMP="$BACKUP_DIR/analytics.sql"
AUTH_DB="$BACKUP_DIR/auth.sqlite3"

for file in "$ANALYTICS_DUMP" "$AUTH_DB"; do
  if [ ! -f "$file" ]; then
    echo "missing backup file: $file" >&2
    exit 1
  fi
done

AUTH_PATH_IN_CONTAINER=$(docker compose exec -T api python -c \
  'import os; print(os.environ.get("AUTH_DATABASE", "/app/db/auth.sqlite3"))' | tr -d '\r')

echo "Restore plan"
echo "  analytics: $ANALYTICS_DUMP  ->  PostgreSQL (replaces existing schema)"
echo "  auth:      $AUTH_DB  ->  $AUTH_PATH_IN_CONTAINER (inside the api volume)"
if [ -f "$BACKUP_DIR/manifest.txt" ]; then
  sed 's/^/  /' "$BACKUP_DIR/manifest.txt"
fi
echo

if [ "$CONFIRM" != "--yes" ]; then
  echo "Dry run. Nothing was changed. Re-run with --yes to apply." >&2
  exit 0
fi

echo "Restoring analytics database..."
docker compose exec -T db sh -c \
  'psql --single-transaction --set ON_ERROR_STOP=1 -U "${POSTGRES_USER:-aeza}" -d "${POSTGRES_DB:-aeza}"' \
  < "$ANALYTICS_DUMP"

echo "Restoring auth database..."
docker compose cp "$AUTH_DB" "api:/tmp/auth-restore.sqlite3" >/dev/null
docker compose exec -T api python - "$AUTH_PATH_IN_CONTAINER" <<'PY'
import os, shutil, sys

target = sys.argv[1]
for suffix in ("-wal", "-shm"):
    try:
        os.remove(target + suffix)
    except FileNotFoundError:
        pass
shutil.copyfile("/tmp/auth-restore.sqlite3", target)
os.chmod(target, 0o600)
print(f"auth database restored to {target}")
PY

echo "Restarting api so it reopens the restored databases..."
docker compose restart api >/dev/null

echo "Waiting for the api to become healthy..."
for _ in $(seq 1 30); do
  if curl -fsS "http://localhost:8000/health" >/dev/null 2>&1; then
    echo "api is healthy."
    break
  fi
  sleep 1
done

echo
echo "Restore complete. Verify the data, not just the process:"
echo "  - log in with an account that existed in the backup"
echo "  - open the dashboard and compare the counts with manifest.txt"
