#!/usr/bin/env bash
# Проверка окружения. Ничего не устанавливает и не меняет.
set -uo pipefail

expected_python="3.12"
failures=0; warnings=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mfail\033[0m  %s\n' "$1"; failures=$((failures+1)); }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; warnings=$((warnings+1)); }

printf '\nИнструменты\n'
command -v docker >/dev/null 2>&1 && ok "docker" || bad "docker не найден (нужен для полного стека)"
command -v node   >/dev/null 2>&1 && ok "node $(node -v)" || bad "node не найден"
command -v npm    >/dev/null 2>&1 && ok "npm $(npm -v)"   || bad "npm не найден"
if command -v python3 >/dev/null 2>&1; then
  pv="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  [ "$pv" = "$expected_python" ] && ok "python $pv" || warn "python $pv, образ использует $expected_python"
else
  bad "python3 не найден"
fi

printf '\nКонфигурация\n'
if [ -f .env ]; then
  ok ".env присутствует"
  grep -qE '^POSTGRES_PASSWORD=.+' .env && ok "POSTGRES_PASSWORD задан" || bad "POSTGRES_PASSWORD пуст (compose не стартует — fail closed)"
else
  warn ".env отсутствует: cp .env.example .env и задайте POSTGRES_PASSWORD"
fi

printf '\nСервисы\n'
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "демон docker доступен"
  if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    ok "база запущена"
  else
    warn "стек не запущен (make compose-up)"
  fi
else
  warn "docker недоступен — доступны только unit-уровни"
fi

printf '\nПорты\n'
for port in 8080 8000; do
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$port "; then warn "порт $port занят"; else ok "порт $port свободен"; fi
done

printf '\n'
if [ "$failures" -gt 0 ]; then printf '\033[31m%d проверок провалено\033[0m, предупреждений: %d\n' "$failures" "$warnings"; exit 1; fi
printf '\033[32mГотово к работе\033[0m, предупреждений: %d\n' "$warnings"
