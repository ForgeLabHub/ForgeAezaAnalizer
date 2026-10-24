# Развёртывание канонического продукта (часть B)

Этот документ описывает развёртывание **`backend/app/` + `frontend/`** —
канонической реализации (см. `docs/ARCHITECTURE_DECISION.md`). Развёртывание
части A (SQLite + `run.sh` + Render) описано в `docs/DEPLOYMENT.md`.

## 1. Состав стека

| Сервис | Образ | Порт | Назначение |
|---|---|---|---|
| `db` | `postgres:16-alpine` | внутренний 5432 | аналитика: снимок, расчёты, настройки модели |
| `api` | `backend/Dockerfile` | 8000 | FastAPI: `/api/v1/*`, `/metrics`, `/health`, `/ready` |
| `web` | `frontend/Dockerfile` | 80 | статика React + прокси `/api` и `/metrics` на `api` |

Публикуются наружу только `web`. Наружу `api` нужен лишь для прямого доступа к
API и метрикам.

## 2. Обязательные переменные окружения

Задаются в `.env` рядом с `docker-compose.yml` (образец — `.env.example`).

| Переменная | Обязательна | Комментарий |
|---|---|---|
| `POSTGRES_PASSWORD` | **да** | без него `docker compose up` не стартует |
| `AEZA_DATABASE_URL` | да | строка подключения к PostgreSQL (её собирает Compose) |
| `AUTH_ISSUER` | для production | HTTPS-домен приложения; локально `http://localhost:8080` |
| `AUTH_FRONTEND_LOGIN_URL` | для production | тот же домен + `/login` |
| `AUTH_COOKIE_SECURE` | для production | `true` вместе с HTTPS-issuer |
| `AEZA_CORS_ORIGINS` | да | список источников вместо `*` |

Аутентификацию обслуживает автономный модуль `backend/auth/` (RS256, отдельная
SQLite). Учётные записи создаются явно:

```bash
docker compose exec api python -m backend.users create analyst@example.com
```

Прежние `AEZA_JWT_SECRET`, `AEZA_ADMIN_EMAIL`, `AEZA_ADMIN_PASSWORD`,
`AEZA_ALLOW_DEV_SECRET` и `AEZA_AUTH_DATABASE_URL` больше **не читаются** кодом
и удалены из `docker-compose.yml`: их требования не давали стартовать чистому
checkout. Модуль отказывается стартовать с HTTPS-issuer и
`AUTH_COOKIE_SECURE=false`, поэтому небезопасная комбинация не проходит.

## 3. Запуск

```bash
cp .env.example .env
# отредактируйте .env: задайте секрет, пароль, источники CORS
docker compose up --build -d
docker compose ps           # все три сервиса должны быть healthy
```

Проверка:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Панель: `http://localhost:8080` (в этом окружении — порт 12000).

## 4. Данные

Порядок загрузки:

1. При **первом** создании каталога `db/postgres/` PostgreSQL выполняет
   `db/analytics_seed.sql` (монтируется в `docker-entrypoint-initdb.d`).
2. Если база аналитики пуста и задан `AEZA_SEED_DEMO_DATA=1`, приложение
   дополнительно применяет JSON из `AEZA_SNAPSHOT_PATH`.
3. Любой другой снимок загружается атомарно:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"analyst@example.com","password":"<пароль учётной записи>"}' \
  | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -X PUT http://localhost:8000/api/v1/source/snapshot \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data-binary @dataset/data.json
```

`PUT /source/snapshot` валидирует структуру и применяет снимок целиком или не
применяет вовсе — частично обновлённого состояния не бывает.

> **Внимание к содержимому seed.** `db/analytics_seed.sql` содержит 60
> аккаунтов: 10 из официального комплекта организатора и 50 синтетических
> (`demo-customer-*`). Подробности и рекомендации — в
> `docs/PROVENANCE_AUDIT.md`, раздел 6.1. Перед демонстрацией убедитесь, что
> состав данных совпадает с тем, что заявлено в README и в деках.

## 5. Миграции схемы

Схема аналитики создаётся приложением при старте (`Database.initialize()`);
отдельный шаг миграций не требуется. Файл `db/schema.sql` описывает схему
SQLite для модуля авторизации части C.

## 6. Наблюдаемость

* `GET /metrics` — формат Prometheus. Доступ: сессия аналитика либо
  `AEZA_METRICS_TOKEN` (Bearer).
* Метки агрегированные, без email и идентификаторов клиентов.
* `/health` — живость процесса; `/ready` — готовность отдавать расчёты.

Пример `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: aeza
    metrics_path: /metrics
    authorization:
      credentials: <AEZA_METRICS_TOKEN>
    static_configs:
      - targets: ["api:8000"]
```

## 7. Обновление и откат

```bash
git pull
docker compose build
docker compose up -d
```

Данные лежат в `db/postgres/` и `db/auth.sqlite3` (тома), поэтому пересборка
образов их не затрагивает. Откат — вернуться на предыдущий коммит и повторить
сборку; при несовместимом изменении схемы восстановите том из резервной копии.

Резервная копия:

```bash
docker compose exec db pg_dump -U aeza aeza > backup-$(date +%F).sql
```

## 8. Безопасность перед публикацией

- [ ] `POSTGRES_PASSWORD` — случайный, не из примера
- [ ] `AUTH_ISSUER` и `AUTH_FRONTEND_LOGIN_URL` указывают на HTTPS-домен
- [ ] `AUTH_COOKIE_SECURE=true`
- [ ] учётные записи созданы с реальными паролями, демо-пароли не используются
- [ ] `AEZA_CORS_ORIGINS` сужен до реальных доменов
- [ ] `api` не опубликован в интернет напрямую
- [ ] `AEZA_METRICS_TOKEN` задан, если `/metrics` доступен извне
- [ ] настроены TLS и резервное копирование томов

## 9. Известные ограничения

* Пересчёт выполняется на каждый запрос (`AnalyticsService.analyze_all()`);
  сортировка и фильтрация — в Python. Для 10–60 клиентов это незаметно, для
  реальной базы потребуется кеш или SQL-выборки (см. `AGENTS.md`).
* `backend/auth/` (часть C) в образ **не** включается — это отдельное
  приложение со своим OIDC-контуром; см. `docs/PROVENANCE_AUDIT.md`, 6.3.
* Секретов в репозитории нет; `.env` не коммитится.
