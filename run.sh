#!/usr/bin/env bash
#
# Aéza Analyzer — one-command launcher.
#
#   ./run.sh                 prepare the environment, import if needed, serve
#   ./run.sh --no-import     skip the initial import (use existing store)
#   ./run.sh --reimport      force a fresh import from the organiser archive
#   ./run.sh --port 9000     serve on another port
#   ./run.sh --host 0.0.0.0  bind to all interfaces (default 127.0.0.1)
#   ./run.sh --help          show usage
#
# Works from any working directory: the project root is derived from the
# script's own location.

set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
cd "$SCRIPT_DIR"

VENV_DIR="${AEZA_VENV_DIR:-$SCRIPT_DIR/.venv}"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
SOURCE_ZIP="${AEZA_SOURCE_ZIP:-$SCRIPT_DIR/датасет.zip}"
DATA_DIR="${AEZA_DATA_DIR:-$SCRIPT_DIR/data}"
DB_FILE="$DATA_DIR/aeza.sqlite"

HOST="${AEZA_HOST:-127.0.0.1}"
PORT="${AEZA_PORT:-8000}"
DO_IMPORT="auto"   # auto | yes | no

usage() {
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-import) DO_IMPORT="no" ;;
        --reimport)  DO_IMPORT="yes" ;;
        --host)      [ $# -ge 2 ] || { echo "run.sh: --host needs a value" >&2; exit 2; }; HOST="$2"; shift ;;
        --port)      [ $# -ge 2 ] || { echo "run.sh: --port needs a value" >&2; exit 2; }; PORT="$2"; shift ;;
        -h|--help)   usage; exit 0 ;;
        *) echo "run.sh: unknown option '$1' (try --help)" >&2; exit 2 ;;
    esac
    shift
done

die() { echo "run.sh: $*" >&2; exit 1; }

# ---------------------------------------------------------------- sanity
[ -f "$REQUIREMENTS" ] || die "requirements.txt not found in $SCRIPT_DIR"
[ -d "$SCRIPT_DIR/aeza_analyzer" ] || die "package aeza_analyzer not found in $SCRIPT_DIR"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON="$candidate"; break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.10+ is required but was not found on PATH"
echo "run.sh: using $($PYTHON --version 2>&1)"

# ---------------------------------------------------------------- venv
if [ ! -d "$VENV_DIR" ]; then
    echo "run.sh: creating virtual environment at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR" || die "failed to create virtual environment"
fi

VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || die "virtual environment at $VENV_DIR looks broken (no bin/python)"

# Install dependencies only when the marker is missing or requirements changed.
STAMP="$VENV_DIR/.requirements.sha256"
WANT_STAMP=$("$PYTHON" - "$REQUIREMENTS" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())
PY
)
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT_STAMP" ]; then
    echo "run.sh: installing dependencies from requirements.txt"
    "$VENV_PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    "$VENV_PY" -m pip install --quiet -r "$REQUIREMENTS" || die "dependency installation failed"
    printf '%s' "$WANT_STAMP" > "$STAMP"
else
    echo "run.sh: dependencies already up to date"
fi

export AEZA_DATA_DIR="$DATA_DIR"

# ---------------------------------------------------------------- import
import_dataset() {
    [ -f "$SOURCE_ZIP" ] || die "source archive not found: $SOURCE_ZIP (expected the organiser dataset)"
    echo "run.sh: importing organiser dataset from $(basename "$SOURCE_ZIP")"
    if ! "$VENV_PY" -m aeza_analyzer.cli import > /tmp/aeza-import.$$.json 2> /tmp/aeza-import.$$.err; then
        echo "run.sh: import failed:" >&2
        cat /tmp/aeza-import.$$.err >&2
        rm -f /tmp/aeza-import.$$.json /tmp/aeza-import.$$.err
        die "aborting: refusing to start on an unusable store"
    fi
    rm -f /tmp/aeza-import.$$.json /tmp/aeza-import.$$.err
}

case "$DO_IMPORT" in
    yes)
        import_dataset
        ;;
    auto)
        if [ -f "$DB_FILE" ]; then
            echo "run.sh: existing store found at $DB_FILE (use --reimport to refresh)"
        else
            import_dataset
        fi
        ;;
    no)
        [ -f "$DB_FILE" ] || die "no store at $DB_FILE and --no-import was given"
        echo "run.sh: using existing store at $DB_FILE"
        ;;
esac

# ---------------------------------------------------------------- serve
case "$HOST" in
    0.0.0.0|::) BROWSE_HOST="127.0.0.1" ;;
    *)          BROWSE_HOST="$HOST" ;;
esac

# Fail early with a clear message instead of a uvicorn bind traceback.
if "$VENV_PY" - "$HOST" "$PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
family = socket.AF_INET6 if ':' in host else socket.AF_INET
probe = socket.socket(family, socket.SOCK_STREAM)
probe.settimeout(1.0)
try:
    probe.bind((host, port))
except OSError:
    raise SystemExit(1)
finally:
    probe.close()
PY
then
    :
else
    die "port ${PORT} on ${HOST} is already in use — stop the other process or pass --port"
fi

cat <<EOF

  Aéza Analyzer is starting.

    Interface : http://${BROWSE_HOST}:${PORT}/
    API docs  : http://${BROWSE_HOST}:${PORT}/docs
    Store     : ${DB_FILE}

  Press Ctrl+C to stop.

EOF

exec "$VENV_PY" -m aeza_analyzer.cli serve --host "$HOST" --port "$PORT"
