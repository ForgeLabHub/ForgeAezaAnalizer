#!/usr/bin/env bash
# Проверка живого инстанса: health, документация API, готовность данных.
#   ./scripts/smoke-test.sh [api-url] [web-url]
#     api-url — по умолчанию http://localhost:8000 (контейнер api)
#     web-url — необязательно: nginx-витрина (http://localhost:8080), тогда
#               проверяется и то, что витрина проксирует API
set -uo pipefail
base="${1:-http://localhost:8000}"
web="${2:-}"
failures=0
ok()  { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad() { printf '  \033[31mfail\033[0m  %s\n' "$1"; failures=$((failures+1)); }

code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$@"; }

printf '\nSmoke test: %s\n' "$base"
c="$(code "$base/health")";      [ "$c" = "200" ] && ok "GET /health -> 200" || bad "GET /health -> $c"
c="$(code "$base/api/v1/docs")"; [ "$c" = "200" ] && ok "GET /api/v1/docs -> 200" || bad "GET /api/v1/docs -> $c"
c="$(code "$base/api/v1/analytics/summary")"
case "$c" in 200|401|403) ok "GET /api/v1/analytics/summary -> $c (эндпоинт существует, доступ контролируется)";; *) bad "GET /api/v1/analytics/summary -> $c";; esac

if [ -n "$web" ]; then
  c="$(code "$web/")";             [ "$c" = "200" ] && ok "GET $web/ (витрина) -> 200" || bad "GET $web/ -> $c"
  c="$(code "$web/health")";       [ "$c" = "200" ] && ok "GET $web/health через прокси -> 200" || bad "GET $web/health -> $c"
  c="$(code "$web/api/v1/docs")";  [ "$c" = "200" ] && ok "GET $web/api/v1/docs через прокси -> 200" || bad "GET $web/api/v1/docs -> $c"
fi

if [ -n "${AEZA_METRICS_TOKEN:-}" ]; then
  c="$(code -H "Authorization: Bearer $AEZA_METRICS_TOKEN" "$base/metrics")"
  [ "$c" = "200" ] && ok "GET /metrics с токеном -> 200" || bad "GET /metrics -> $c"
else
  echo "  skip  /metrics: AEZA_METRICS_TOKEN не задан"
fi

printf '\n'
[ "$failures" -gt 0 ] && { printf '\033[31mпровалено: %d\033[0m\n' "$failures"; exit 1; }
printf '\033[32mSmoke test пройден\033[0m\n'
