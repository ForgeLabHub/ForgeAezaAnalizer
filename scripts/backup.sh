#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
ROOT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd -P)
cd "$ROOT_DIR"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="${1:-$ROOT_DIR/backups/$STAMP}"
mkdir -p "$OUT_DIR"

echo "Backing up to $OUT_DIR"

echo "  analytics.sql"
docker compose exec -T db sh -c \
  'pg_dump --clean --if-exists -U "${POSTGRES_USER:-aeza}" -d "${POSTGRES_DB:-aeza}"' \
  > "$OUT_DIR/analytics.sql"

echo "  auth.sqlite3"
docker compose exec -T api python - <<'PY' > "$OUT_DIR/auth.sqlite3"
import os, sqlite3, sys

source = os.environ.get("AUTH_DATABASE", "/app/db/auth.sqlite3")
target = "/tmp/auth-backup.sqlite3"
for path in (target, target + "-wal", target + "-shm"):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

if os.path.exists(source):
    destination = sqlite3.connect(target)
    sqlite3.connect(source).backup(destination)
    destination.close()
else:
    sqlite3.connect(target).close()

with open(target, "rb") as handle:
    sys.stdout.buffer.write(handle.read())
PY

{
  echo "created_at_utc=$STAMP"
  echo "git_commit=$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "analytics_dump_bytes=$(wc -c < "$OUT_DIR/analytics.sql" | tr -d ' ')"
  echo "auth_backup_bytes=$(wc -c < "$OUT_DIR/auth.sqlite3" | tr -d ' ')"
} > "$OUT_DIR/manifest.txt"

python3 - "$OUT_DIR/auth.sqlite3" <<'PY'
import sqlite3, sys

with sqlite3.connect(sys.argv[1]) as connection:
    tables = sorted(row[0] for row in connection.execute(
        "select name from sqlite_master where type='table'"))
if tables:
    print("  auth tables:", ", ".join(tables))
else:
    print("  warning: auth backup has no tables (no accounts created yet)", file=sys.stderr)
PY

echo "Backup complete:"
ls -lh "$OUT_DIR"
echo
echo "Next: restore it into a scratch stack with scripts/restore.sh and check /health."
