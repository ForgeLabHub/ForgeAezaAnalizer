# Индекс документации

Точка входа. Существующие документы сохранены; этот индекс объясняет, что где искать
и что из этого проверяется автоматически.

| Вопрос | Документ |
| --- | --- |
| Запустить с нуля | [../BUILD.md](../BUILD.md), [DEPLOYMENT_PART_B.md](DEPLOYMENT_PART_B.md) |
| Как устроено приложение и расчёты | [PROJECT_GUIDE.md](PROJECT_GUIDE.md), [architecture/system-context.md](architecture/system-context.md) |
| Почему такие границы модулей | [architecture/system-context.md](architecture/system-context.md) |
| Как устроены данные и применение схемы | [database/schema.md](database/schema.md), [database/migrations.md](database/migrations.md) |
| API: соглашения, ошибки | [api/conventions.md](api/conventions.md), `../backend/openapi.json` |
| Что делает конкретная функция / что заимствовать | [modules/](modules/), [modules/module-map.md](modules/module-map.md) |
| Эксплуатация, метрики, обновления | [operations/deployment.md](operations/deployment.md), [operations/monitoring.md](operations/monitoring.md) |
| Учётные записи и вход | [AUTH_MODULE.md](AUTH_MODULE.md) |
| Telegram Mini App | [TELEGRAM_BOT.md](TELEGRAM_BOT.md) |
| Почта | [EMAIL.md](EMAIL.md) |
| AI Analyst и ассистент | [AI_ANALYST.md](AI_ANALYST.md), [AI_ASSISTANT.md](AI_ASSISTANT.md) |
| Данные и снимок | [../dataset/README.md](../dataset/README.md) |
| Стиль кода и линт | [development/code-style.md](development/code-style.md) |
| Чем доказано, что всё работает | [verification/matrix.md](verification/matrix.md), CI |
| Английская версия документации | [en/index.md](en/index.md) · PDF в [pdf/](pdf/) |
| Найденные разрывы и что исправлено | [audit/portability-audit-2026-10-29.md](audit/portability-audit-2026-10-29.md) |

## Правила

1. `backend/openapi.json` **генерируется** (`make openapi`), проверяется в CI
   (`make openapi-check`).
2. `backend/scripts/check_docs.py` уже проверяет: живые ссылки, существование
   `AEZA_*` в `.env.example`, реальность упомянутых маршрутов, отсутствие
   секретоподобных примеров. `scripts/docs-check.sh` добавляет проверку структуры и
   полноты спецификаций модулей.
3. Новый модуль без спецификации по [modules/module-template.md](modules/module-template.md)
   не считается готовым — проверяется в CI.
4. Документ, утверждающий поведение, обязан иметь строку в
   [verification/matrix.md](verification/matrix.md): утверждение → команда → CI.

## Управление проектом

- `forge.sh` / `forge.bat` — запуск, остановка, логи, тесты, база и контейнеры одной командой; см. раздел в README.
