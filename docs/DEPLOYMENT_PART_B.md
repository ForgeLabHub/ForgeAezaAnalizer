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

Compose публикует `web` на `8080`, API на `8000`; ограничьте доступ к API
правилами reverse proxy и firewall.

## 2. Обязательные переменные окружения

Задаются в `.env` рядом с `docker-compose.yml` (образец — `.env.example`).

| Переменная | Обязательна | Комментарий |
|---|---|---|
| `POSTGRES_PASSWORD` | **да** | пароль PostgreSQL; Compose использует его для подключения API |
| `AUTH_ISSUER` | production | публичный HTTPS origin приложения |
| `AUTH_FRONTEND_LOGIN_URL` | production | HTTPS URL страницы входа |
| `AUTH_COOKIE_SECURE` | production | задайте `true` при HTTPS |
| `AEZA_CORS_ORIGINS` | да | origin интерфейса |

Пользователи и хеши паролей хранятся в SQLite `auth_data`; первого пользователя
создайте вручную после запуска стека.

## 3. Запуск

```bash
cp .env.example .env
# отредактируйте .env: задайте пароль PostgreSQL и production auth origins
docker compose up --build -d
docker compose ps           # db healthy; api и web запущены
docker compose exec api python -m backend.users create analyst@example.com
```

Проверка:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

Панель: `http://localhost:8080` (в этом окружении — порт 12000).

## 4. Данные

Порядок загрузки:

1. При пустой базе приложение валидирует и загружает официальный снимок из
   `AEZA_SNAPSHOT_PATH` атомарно.
2. Любой другой снимок загружается через API:

```bash
read -r -p "Login: " LOGIN
read -r -s -p "Password: " LOGIN_PASSWORD
printf '\n'
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$LOGIN\",\"password\":\"$LOGIN_PASSWORD\"}" \
  | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -X PUT http://localhost:8000/api/v1/source/snapshot \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data-binary @dataset/data.json
```

`PUT /source/snapshot` валидирует структуру и применяет снимок целиком или не
применяет вовсе — частично обновлённого состояния не бывает.

## 5. Миграции схемы

Схема аналитики создаётся приложением при старте (`Database.initialize()`);
отдельный шаг миграций не требуется. `db/schema.sql` описывает таблицу
пользователей auth SQLite.

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

Данные лежат в именованных Docker volumes `pg_data` и `auth_data`, поэтому
пересборка образов их не затрагивает. Откат — вернуться на предыдущий коммит и
повторить сборку; при несовместимом изменении схемы восстановите том из
резервной копии.

### Резервная копия и восстановление

Резервную копию и восстановление выполняют два скрипта, а не одна команда:
`scripts/backup.sh` снимает оба хранилища, `scripts/restore.sh` возвращает их.

```bash
./scripts/backup.sh                 # ./backups/<UTC-метка>/{analytics.sql,auth.sqlite3,manifest.txt}
./scripts/restore.sh backups/<метка>          # пробный запуск: печатает план, ничего не меняет
./scripts/restore.sh backups/<метка> --yes    # применить
```

`backup.sh` снимает дамп аналитической БД через `pg_dump` и копию
`auth.sqlite3` через штатный online-backup API SQLite, поэтому конкурентная
запись не рвёт файл. `manifest.txt` фиксирует коммит и размеры — по нему
проверяют, что восстановлено именно то, что снимали.

Восстановление без `--yes` ничего не делает: сначала посмотрите план. После
применения проверьте **данные**, а не только процесс: войдите учётной записью из
копии и сверьте числа на дашборде с манифестом. Непроверенное восстановление
резервной копией не является.

## 8. Безопасность перед публикацией

- [ ] создан отдельный пользователь через `backend.users create`
- [ ] `AUTH_ISSUER` и `AUTH_FRONTEND_LOGIN_URL` используют HTTPS origin
- [ ] `AUTH_COOKIE_SECURE=true`
- [ ] `AEZA_CORS_ORIGINS` сужен до реальных доменов
- [ ] доступ к API ограничен правилами reverse proxy и firewall
- [ ] `AEZA_METRICS_TOKEN` задан, если `/metrics` доступен извне
- [ ] настроены TLS и резервное копирование томов

## 9. Известные ограничения

* Пересчёт выполняется на каждый запрос (`AnalyticsService.analyze_all()`);
  сортировка и фильтрация — в Python. Для 10–60 клиентов это незаметно, для
  реальной базы потребуется кеш или SQL-выборки (см. `AGENTS.md`).
* Учётные записи хранятся отдельно от аналитических данных в SQLite volume
  `auth_data`; пользователь создаётся вручную через CLI.
* Секретов в репозитории нет; `.env` не коммитится.
