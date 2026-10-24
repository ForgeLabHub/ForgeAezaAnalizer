# Тестирование и проверки

Все результаты ниже получены **фактическим запуском** команд на актуальном
коде. Не проверенные пункты помечены явно.

## Тестовые наборы

| Компонент | Команда | Результат |
|---|---|---|
| B: основной продукт | `python -m pytest backend/tests -q` | **210 passed** |
| C: auth-модуль | `python -m pytest tests/test_auth.py -q` | **17 passed** |
| A: анализатор | `python -m pytest tests -q --ignore=tests/test_auth.py` | **52 passed** |
| Всё вместе | `python -m pytest backend/tests tests -q` | **279 passed** |

**Итого 279 тестов**, все проходят (проверено 2026-10-24).

Два набора — это два стека: `backend/tests` тестирует платформу
(`backend/app/`), `tests` — вспомогательный анализатор (`aeza_analyzer/`,
см. `docs/DATA_ARCHITECTURE.md`).

## Сборка фронтенда

```bash
cd frontend && npm ci && npm run build
```

Результат: `tsc -b && vite build` — успешно, без ошибок типизации.

```
dist/index.html                   0.98 kB │ gzip:  0.60 kB
dist/assets/index-*.css          21.09 kB │ gzip:  5.41 kB
dist/assets/index-*.js          218.00 kB │ gzip: 68.93 kB
✓ built in 992ms
```

## Проверка основного продукта (B) на живом сервере

Запуск:

```bash
cd backend
export AEZA_JWT_SECRET=... AEZA_ADMIN_EMAIL=analyst@aeza.test \
       AEZA_ADMIN_PASSWORD=... AEZA_SEED_DEMO_DATA=1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8210
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
         high = 3, medium = 3, not_applicable = 4
customers[0]: user-0010@example.test, riskScore 71.4, riskCategory "high",
              balance {cents: 20379, eur: "203.79"},
              topReasons: ["Близость даты окончания: Услуга истекла 35.0 дн. назад..."]
```

### Изменение коэффициентов и пересчёт

| Действие | `highRisk` |
|---|---|
| До изменения | 3 |
| `PATCH {"weights":{"expiry_proximity":0.5}}` | **0** (низкий риск 0 → 1, выручка 5,80 € → 4,37 €) |
| `POST /api/v1/model/settings/reset` | 3 (восстановлено) |

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
| Нагрузочное тестирование | вне объёма задачи |

## Интерактивная проверка UI в браузере

Выполнена на собранном фронтенде (`vite preview`, порт 4210) с проксированием
`/api` на живой backend (порт 8010) и реальным снимком организатора.

Проверено (Chromium через Playwright MCP):

| Проверка | Наблюдаемый результат |
|---|---|
| Вход в приложение | заголовок «Aéza · Churn Risk Analyzer», навигация доступна |
| Дашборд показывает реальные данные | 10 клиентов, 18 открытых услуг, 3 клиента высокого риска, выручка под риском 5,80 €, предстоящие продления 17,03 € |
| Единицы денег | все суммы с «€» и двумя знаками; баланс и исторические пополнения показаны отдельно от выручки под риском |
| Распределение риска | 3 высокий / 3 средний / 4 «не применимо» — совпадает с `byCategory` из API |
| Центр действий | очереди «Операционная проблема (3)», «Плановый обзор (7)»; категории, фильтр, сортировки |
| Сортировка по ID | `sortBy=id&sortDir=desc` → 10,9,…,1; повторный клик → `asc` → 1,2,…,10 (числовая, не лексикографическая) |
| Поиск без совпадений | «Ничего не найдено…», 0 записей, кнопка «Сбросить» |
| Карточка клиента | балл 71.4/100, причины по каждой услуге, рекомендации, «Недостаточно данных» для неполных факторов |
| Лаборатория сценариев | вес «Близость даты окончания» 3 → 6, сравнение: выручка под риском 5,80 € → 6,94 € (+1,14 €) |
| Изоляция сценария | после прогона `GET /model/settings` → `isDefault: true`, веса не изменились |
| Сохранение настроек | `PATCH` веса 3 → 6 → `modelVersion 2`, `isDefault false`, `generation 2`, выручка 5,80 € → 6,94 € |
| Сброс настроек | `POST /model/settings/reset` → `modelVersion 3`, `isDefault true`, выручка вернулась к 5,80 € |
| Мобильная вёрстка 390×844 | на дашборде, центре действий, сценариях, клиентах и карточке `pageOverflow: false`; таблица скроллится внутри `.table-wrap` (`overflow-x: auto`, 1229 px контента в 364 px контейнера) |
| Ошибки в консоли | 0 errors, 0 warnings |

Ограничение: это ручная проверка через инструмент автоматизации браузера, а не
зафиксированный E2E-набор в CI. Регрессионного прогона при следующих изменениях
фронтенда нет.

### Проверка развёрнутого стека (Docker Compose)

Те же сценарии пройдены на собранном стеке `docker compose` (nginx `web` →
порт 12000, API → порт 12001, PostgreSQL 16) — то есть на пути «образ +
миграции + Postgres», а не на SQLite.

| Проверка | Наблюдаемый результат |
|---|---|
| Совпадение образов и HEAD | раздаваемые `assets/index-*.js|css` совпадают с `frontend/dist` |
| Вход через UI | `/login` → демо-доступ → дашборд |
| Дашборд | 10 клиентов, 3 высокого риска, выручка под риском 5,80 €, предстоящие продления 17,03 €, исторические пополнения 22 240,73 € |
| Карточка клиента #5 | 71.4/100 «Высокий»; «Показать все факторы (7)» раскрывает факторы с весом и вкладом; причины и рекомендации по каждой услуге |
| Сортировка по балансу | asc 34,78 → 203,79 → 286,57 → 320,98 €; desc 915,06 → 886,96 → 838,10 € (числовая) |
| Лаборатория сценариев | вес «Близость даты окончания» 3 → 6: 5,80 € → 6,94 € (+1,14 €); изоляция подтверждена (`isDefault: true` после прогона) |
| Сохранение настроек | вес «Услуга приостановлена» 1 → 3: сумма весов 13 → 15, выручка 5,80 € → 6,45 €, `modelVersion 3`, `isDefault false`; сброс → `modelVersion 4`, 5,80 € |
| Мобильная вёрстка 390×844 | на всех шести страницах `scrollWidth == clientWidth` (без переполнения) |
| `/metrics` | без токена 401; с токеном `aeza_customers_total 10`, `aeza_services_total 30`, `aeza_revenue_at_risk_eur 5.8`; PII в labels отсутствует |
| Ошибки в консоли | только ожидаемый `401 /auth/me` до входа |

**Найдено при проверке:** настройки модели хранятся в томе `pgdata`, поэтому
после `docker compose up --build` уже существующая база сохраняла устаревшие
веса (`failed_renewals: 2.0`, `suspended_status: 2.0`,
`renewal_failure_rate: 1.5`), и опубликованный расчёт отличался от значений по
умолчанию (5,74 € против 5,80 €; 3 против 4 услуг высокого риска). Лечится
`POST /api/v1/model/settings/reset`; шаг описан в README.

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

> **Если тесты падают с `Fatal Python error: Segmentation fault`** ещё до
> сбора результатов (в стеке виден `asyncio/base_events.py` →
> `anyio/from_thread.py`), причина не в коде. Проверьте `LD_LIBRARY_PATH`:
> в среде агента он содержит путь для другой архитектуры
> (`/usr/lib/aarch64-linux-gnu` на x86_64), из-за чего CPython загружает
> несовместимые библиотеки и `_asyncio` падает. Обход:
>
> ```bash
> env -u LD_LIBRARY_PATH python -m pytest tests/ -q
> ```
