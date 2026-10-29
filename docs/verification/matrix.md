# Матрица проверок

| Проверка | Что доказывает | Команда | CI |
| --- | --- | --- | --- |
| Тесты backend | домен и API корректны | `make test-backend` | `ci.yml` → `backend` |
| Тесты аутентификации без PostgreSQL | модуль входа независим от аналитики | `make test-auth` | `ci.yml` → `backend` |
| Проверка зависимостей фронтенда | UI собирается воспроизводимо | `make test-frontend` | `ci.yml` → `frontend` |
| Спецификация API совпадает с кодом | документация не врёт о маршрутах | `make openapi-check` | `portability.yml` → `contract` |
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
