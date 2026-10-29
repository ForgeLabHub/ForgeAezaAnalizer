# Матрица проверок

| Проверка | Что доказывает | Команда | CI |
| --- | --- | --- | --- |
| Тесты backend | домен и API корректны | `make test-backend` | `ci.yml` → `backend` |
| Тесты аутентификации без PostgreSQL | модуль входа независим от аналитики | `make test-auth` | `ci.yml` → `backend` |
| Проверка зависимостей фронтенда | UI собирается воспроизводимо | `make test-frontend` | `ci.yml` → `frontend` |
| Спецификация API совпадает с кодом | документация не врёт о маршрутах | `make openapi-check` | `portability.yml` → `contract` |
| Генерация спецификации идемпотентна | повторный экспорт не меняет файл | `make openapi && git diff --exit-code backend/openapi.json` | `portability.yml` → `contract` |
| Стек готов до проверок | smoke-тест не гоняется с приложением наперегонки | `make wait` | все job'ы `portability.yml` |
| Витрина проксирует API | nginx-слой действительно работает, а не только api | `make smoke-test` (проверяет `:8000` и `:8080`) | `portability.yml` → `compose-smoke` |
| Документация согласована | ссылки живые, переменные и маршруты существуют | `make docs-check` | `ci.yml` → `docs`, `portability.yml` → `docs` |
| Compose падает без секрета | прод-конфигурация не может быть пустой | `docker compose config` | `ci.yml` → `compose` |
| Полный стек поднимается | сервисы действительно взаимодействуют | `make compose-up` + `make smoke-test` | `portability.yml` → `compose-smoke` |
| Повторный старт безопасен | применение схемы идемпотентно | два запуска api подряд | `portability.yml` → `upgrade-path` |
| Backup → restore → smoke | данные восстанавливаются, а не только копируются | `make backup` → `make restore` → `make smoke-test` | `portability.yml` → `backup-restore` |
| Запуск без опциональных интеграций | AI/Telegram/почта — опции, а не условие старта | `make compose-up` без них | `portability.yml` → `config-without-secrets` |
| Проверка хоста | окружение пригодно до запуска | `make doctor` | локально |

## Что сознательно не проверяется

- Качество ответов LLM: проверяется только то, что цифры берутся из домена.
- Производительность и нагрузка (есть `backend/scripts/loadtest.py`, но он не в CI).
- Несколько реплик api: состояние Telegram-сессий и снимка живёт в процессе.
