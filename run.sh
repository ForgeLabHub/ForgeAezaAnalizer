#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT_DIR"

usage() {
    cat <<'EOF'
Usage: ./run.sh [up|status|logs|down]

  up      Build and start the Compose stack (default)
  status  Show Compose service status
  logs    Follow Compose logs
  down    Stop services without deleting volumes
EOF
}

die() {
    printf 'run.sh: %s\n' "$1" >&2
    exit 1
}

ACTION="${1:-up}"
shift || true

case "$ACTION" in
    -h|--help|help)
        usage
        exit 0
        ;;
esac

command -v docker >/dev/null 2>&1 || die "Docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is required"

case "$ACTION" in
    up)
        [[ $# -eq 0 ]] || die "up does not accept extra arguments"
        [[ -f .env ]] || die "create .env from .env.example and set POSTGRES_PASSWORD"
        POSTGRES_PASSWORD_VALUE="$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | head -n 1 | tr -d '\r')"
        [[ -n "$POSTGRES_PASSWORD_VALUE" && "$POSTGRES_PASSWORD_VALUE" != "change-me-too" ]] \
            || die "set a non-placeholder POSTGRES_PASSWORD in .env"
        docker compose config --quiet
        docker compose up --build -d
        docker compose ps
        printf '\nInterface: http://localhost:8080\nAPI docs:  http://localhost:8000/api/v1/docs\n'
        ;;
    status)
        docker compose ps "$@"
        ;;
    logs)
        docker compose logs --follow --tail=100 "$@"
        ;;
    down)
        [[ $# -eq 0 ]] || die "down does not accept options; data volumes are preserved"
        docker compose down
        ;;
    *)
        usage >&2
        die "unknown action: $ACTION"
        ;;
esac
