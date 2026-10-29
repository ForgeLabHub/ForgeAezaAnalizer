# Развёртывание

Основной способ — Docker Compose (`docker-compose.yml`, помощник `./run.sh` или
`make compose-up`). Подробные шаги по обновлению и копиям — в существующем
[DEPLOYMENT_PART_B.md](../DEPLOYMENT_PART_B.md); здесь — контрольный список.

## Порядок

```bash
cp .env.example .env
# обязательно: POSTGRES_PASSWORD (compose намеренно падает без него)
make doctor
make compose-up
make smoke-test API_URL=http://localhost:8000
make create-user EMAIL=analyst@example.com
```

UI: `http://localhost:8080`, API: `http://localhost:8000/api/v1/docs`.

## Что обязательно решить перед продом

1. **Секреты.** `POSTGRES_PASSWORD`, `AUTH_PRIVATE_KEY` (JWT), `AEZA_SOURCE_INGEST_TOKEN`,
   `AEZA_METRICS_TOKEN`, `AEZA_TELEGRAM_WEBHOOK_SECRET`. Ни один не имеет дефолта,
   пригодного для продакшена.
2. **Fail closed.** Compose требует `POSTGRES_PASSWORD` (`:?`) — это проверяется в CI
   отдельным заданием. Не ослабляйте эту защиту.
3. **TLS.** `AUTH_COOKIE_SECURE=true` и HTTPS-терминация на прокси.
4. **CORS.** `AEZA_CORS_ORIGINS` — точный список, не `*`.
5. **Резервные копии.** Две базы → две копии: PostgreSQL и SQLite (`AUTH_DATABASE`).
   `make backup` покрывает обе; проверка восстановления — в CI.
6. **AI.** `AEZA_AI_ENABLED=0` по умолчанию. Включайте осознанно: это внешний вызов с
   таймаутом до `AEZA_AI_TIMEOUT_SECONDS` (по умолчанию 420 с).

## Разделение ролей

| Роль | Порты | Доступ |
| --- | --- | --- |
| `web` (nginx + статика) | 8080 | публично |
| `api` (FastAPI) | 8000 | только изнутри сети, наружу — через web/прокси |
| `db` (PostgreSQL) | 5432 | только изнутри |

Публиковать `api` наружу напрямую не следует: `/metrics` и служебные маршруты
защищены токеном, но граница сети дешевле, чем доверие к конфигурации.

## Проверка после развёртывания

```bash
make smoke-test API_URL=http://localhost:8000
./scripts/smoke-test.sh http://localhost:8080   # через web/прокси
```
