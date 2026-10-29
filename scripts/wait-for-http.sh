#!/usr/bin/env bash
# Ждёт, пока URL начнёт отвечать HTTP 200. Ничего не меняет в системе.
#   ./scripts/wait-for-http.sh <url> [секунды]
set -uo pipefail
url="${1:?укажите url}"
limit="${2:-120}"
for _ in $(seq 1 "$limit"); do
  if curl -fsS -m 3 -o /dev/null "$url"; then
    printf '  \033[32mok\033[0m    %s отвечает\n' "$url"
    exit 0
  fi
  sleep 1
done
printf '  \033[31mfail\033[0m  %s не ответил за %s с\n' "$url" "$limit" >&2
exit 1
