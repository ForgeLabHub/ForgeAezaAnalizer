# Тестирование и проверки

Все результаты ниже получены **фактическим запуском** команд на актуальном
коде. Не проверенные пункты помечены явно.

## Тестовые наборы

Числа получены фактическим запуском на текущем коде (проверено 2026-10-24):

| Компонент | Команда | Результат |
|---|---|---|
| B: основной продукт | `cd backend && python -m pytest tests/ -q` | **246 passed** |
| C: auth-модуль | `python -m pytest tests/test_auth.py -q` (из корня) | **17 passed** |
| A: анализатор | `python -m pytest tests/ -q --ignore=tests/test_auth.py` (из корня) | **52 passed** |
| Всё вместе (корень: A + C) | `python -m pytest tests/ -q` | **69 passed** |

Итого: **246** тестов части B и **69** тестов корневого набора (52 части A + 17
части C), все проходят. Предыдущая редакция этого документа указывала 108/177 —
это устаревшие значения; они заменены на фактические.

## Сборка фронтенда

```bash
cd frontend && npm ci && npm run build
```

Результат: `tsc -b && vite build` — успешно, без ошибок типизации.

```
dist/index.html                   0.97 kB │ gzip:  0.59 kB
dist/assets/index-*.css          30.43 kB │ gzip:  6.92 kB
dist/assets/index-*.js          264.74 kB │ gzip: 83.28 kB
✓ 50 modules transformed, built in 1.03s
```

## Проверка основного продукта (B) на живом сервере

Запуск:

```bash
# из корня репозитория
export AEZA_JWT_SECRET=... AEZA_ADMIN_EMAIL=analyst@aeza.test \
       AEZA_ADMIN_PASSWORD=... AEZA_SEED_DEMO_DATA=1 \
       AEZA_SNAPSHOT_PATH=backend/data/snapshot.json \
       AEZA_ANALYTICS_FACTORY=backend.app.domain.module:create
python -m uvicorn main:app --host 127.0.0.1 --port 8210
```

### Критерии приёмки ТЗ

| Проверка | Команда | Результат |
|---|---|---|
| Health | `curl /health` | `200` |
| Метрики | `curl /metrics` | `200`, 31 строка Prometheus |
| Swagger | `curl /api/v1/docs` | `200` |
| OpenAPI | `curl /api/v1/openapi.json` | `200` |
| **API защищён без токена** | `curl /api/v1/customers` | **`401`** |
| То же для summary | `curl /api/v1/analytics/summary` | **`401`** |

### Авторизация

```bash
curl -X POST /api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"analyst@aeza.test","password":"..."}'
```

Результат: `access_token` длиной 184 символа (JWT).

### Все обязательные эндпоинты с токеном

| Эндпоинт | Результат |
|---|---|
| `GET /api/v1/auth/me` | `200` |
| `GET /api/v1/customers` | `200` |
| `GET /api/v1/analytics/summary` | `200` |
| `GET /api/v1/model/settings` | `200` |
| `GET /api/v1/source/snapshot` | `200` |

### Реальные данные (не заглушки)

```
summary: customers.total = 10, services.total = 30
         high = 2, medium = 4, not_applicable = 4
customers[0]: user-0010@example.test, riskScore 73.3, riskCategory "high",
              balance {cents: 20379, eur: "203.79"},
              topReasons: ["Близость даты окончания: Услуга истекла 35.0 дн. назад..."]
```

### Изменение коэффициентов и пересчёт

| Действие | `highRisk` |
|---|---|
| До изменения | 2 |
| `PATCH {"weights":{"expiry_proximity":0.5}}` | **1** |
| `POST /api/v1/model/settings/reset` | 2 (восстановлено) |

Значение веса после PATCH: `0.5`; после reset: `3.0` (значение по умолчанию).
Это доказывает, что критерий A6 ТЗ («изменение коэффициента вызывает пересчёт»)
выполняется.

### Метрики Prometheus

```
# HELP aeza_customers_total Number of customers in the current dataset
# TYPE aeza_customers_total gauge
aeza_customers_total 0.0
# HELP aeza_services_total Number of services in the current dataset
...
```

Формат соответствует требованиям Prometheus (HELP/TYPE/значение), кардинальность
низкая — email и ID клиентов в метки не попадают.

## Проверка анализатора (A)

| Проверка | Команда | Результат |
|---|---|---|
| Импорт датасета | `python -m aeza_analyzer.cli import` | 10 / 30 / 100, rejected 0 |
| Профиль данных | `python -m aeza_analyzer.cli audit` | JSON-профиль |
| Тесты | `pytest tests/ --ignore=tests/test_auth.py` | 52 passed |
| `run.sh` синтаксис | `bash -n run.sh` | OK |
| `run.sh` из другого каталога | `bash /path/run.sh --port 8099` из `/tmp` | venv + импорт + сервер, `200` |
| Повторный запуск | повторный `run.sh` | «existing store found», хеш БД не изменился |
| Остановка | `kill -INT` | 0 оставшихся процессов |
| Конфликт порта | `run.sh --port <занятый>` | сообщение + exit 1 |

## Негативные проверки

| Сценарий | Ожидание | Результат |
|---|---|---|
| Запрос без токена | 401 | 401 ✅ |
| Логин без поля `email` | 422 | 422 ✅ |
| Повреждённая БД (A) | понятная ошибка, exit 2 | ✅ |
| Ошибочный импорт (A) | 400, данные целы | ✅ |
| Path traversal в ZIP (A) | отказ | ✅ (`test_archive.py`) |

## Что НЕ проверялось

| Пункт | Причина |
|---|---|
| `docker compose up --build` | в окружении нет активного Docker-демона (`docker info` недоступен) |
| PostgreSQL как БД | используется SQLite; `psycopg` установлен, но подключение к PG не выполнялось |
| OIDC-поток с внешним провайдером | проверен только юнит-тестами `backend/auth` |
| React UI в браузере | сборка и типизация проверены; интерактивная проверка страниц B не проводилась |
| Нагрузочное тестирование | вне объёма задачи |

## Воспроизведение

```bash
# основной продукт (B)
cd backend && python -m pytest tests/ -q

# фронтенд
cd frontend && npm ci && npm run build

# вспомогательный инструмент (A)
python -m pytest tests/ -q --ignore=tests/test_auth.py
./run.sh
```
