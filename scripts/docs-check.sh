#!/usr/bin/env bash
# Проверка документации: обязательные файлы, живые ссылки, полнота спецификаций модулей.
set -uo pipefail
failures=0
ok()  { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad() { printf '  \033[31mfail\033[0m  %s\n' "$1"; failures=$((failures+1)); }

printf '\nОбязательные документы\n'
required=(
  README.md BUILD.md
  docs/README.md docs/index.md
  docs/architecture/system-context.md
  docs/database/schema.md docs/database/migrations.md
  docs/api/conventions.md
  docs/operations/deployment.md docs/operations/monitoring.md
  docs/verification/matrix.md
  docs/modules/module-template.md
)
for f in "${required[@]}"; do [ -s "$f" ] && ok "$f" || bad "$f отсутствует или пуст"; done

printf '\nСпецификации модулей\n'
shopt -s nullglob
headings=("Назначение" "Сценарии" "Контракт" "Данные" "Права" "Зависимости" "Конфигурация" "Сборка" "Тесты" "Наблюдаемость" "Ограничения")
module_ok=1
for m in docs/modules/*.md; do
  case "$m" in *module-template.md) continue ;; esac
  for h in "${headings[@]}"; do
    if ! grep -qi "$h" "$m"; then bad "$m: нет раздела «$h»"; module_ok=0; fi
  done
done
[ "$module_ok" -eq 1 ] && ok "все спецификации содержат 11 разделов"

printf '\nСсылки\n'
broken=0
while IFS= read -r line; do
  file="${line%%:*}"; target="$(printf '%s' "$line" | sed -n 's/.*](\([^)#]*\).*/\1/p')"
  [ -z "$target" ] && continue
  case "$target" in http*|mailto:*|\#*) continue ;; esac
  base="$(dirname "$file")"
  if [ ! -e "$base/$target" ] && [ ! -e "$target" ]; then bad "$file -> $target (битая ссылка)"; broken=$((broken+1)); fi
done < <(grep -rnoE '\[[^]]*\]\([^)]+\)' --include='*.md' . 2>/dev/null)
[ "$broken" -eq 0 ] && ok "битых относительных ссылок нет"

printf '\nОтладочные артефакты\n'
stray="$(find . -type f \( -name '*.bak*' -o -name '*.fixbak' -o -name '*.orig' \) -not -path './.git/*' | head -5)"
[ -z "$stray" ] && ok "временных копий в репозитории нет" || { bad "в репозитории лежат копии: $stray"; }

printf '\n'
if [ "$failures" -gt 0 ]; then printf '\033[31m%d проблем в документации\033[0m\n' "$failures"; exit 1; fi
printf '\033[32mДокументация согласована\033[0m\n'
