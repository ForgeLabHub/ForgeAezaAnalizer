# Архитектура

## Обзор

Aéza Analyzer — монолитное Python-приложение: FastAPI-сервис с встроенным
SQLite-хранилищем и статическим SPA. Внешних сервисов и очередей нет.

```mermaid
flowchart TD
    A[датасет.zip] -->|safe_extract| B[распакованный каталог]
    B -->|data.json| C[validation.py<br/>валидация по контракту]
    C -->|валидные записи| D[loader.py<br/>одна транзакция]
    C -.->|отклонённые строки| E[отчёт импорта]
    D --> F[(SQLite<br/>data/aeza.sqlite)]
    F --> G[analytics/service.py<br/>риск + выручка]
    G --> H[api/app.py<br/>FastAPI]
    H --> I[static/<br/>SPA]
    J[risk_weights] --- F
    K[import_runs, meta] --- F
```

## Слои

| Слой | Модули | Ответственность | Зависит от |
|---|---|---|---|
| Конфигурация | `config.py` | пути из env, ленивые свойства | — |
| Деньги | `money.py` | евроценты → евро (100:1) | — |
| Хранение | `models.py`, `db.py` | ORM-модели, engine, проверка хранилища | config, models |
| Импорт | `importer/archive.py`, `validation.py`, `loader.py` | распаковка, валидация, атомарная загрузка | db, models |
| Аналитика | `analytics/risk.py`, `analytics/service.py` | скоринг, агрегация, выручка | models |
| Аудит | `audit.py` | воспроизводимый профиль данных | models |
| API | `api/app.py`, `api/schemas.py` | REST, конвертация в евро | analytics, importer |
| CLI | `cli.py` | `import` / `audit` / `serve` | все слои |
| UI | `static/*` | SPA, работа с API | API |

Слои не пересекаются: аналитика не знает про HTTP, импорт — про аналитику,
API — про формулы.

## Последовательность импорта

```mermaid
sequenceDiagram
    participant CLI as cli/run.sh
    participant AR as archive.py
    participant VA as validation.py
    participant LO as loader.py
    participant DB as SQLite

    CLI->>AR: safe_extract(датасет.zip)
    AR->>AR: проверка traversal/дубликатов/ratio
    AR-->>CLI: каталог + sha256
    CLI->>VA: validate_accounts/services/transactions
    VA->>VA: типы, диапазоны, ISO-UTC, FK
    alt есть отклонённые и strict=True
        VA-->>CLI: ValueError → откат, ничего не записано
    else все валидны
        VA-->>LO: нормализованные записи
        LO->>DB: BEGIN
        LO->>DB: DELETE transactions → services → accounts
        LO->>DB: INSERT accounts → services → transactions
        LO->>DB: UPSERT meta (reference_at, sha256)
        LO->>DB: INSERT import_runs
        LO->>DB: COMMIT
        LO-->>CLI: ImportResult (счётчики, отклонённые)
    end
```

## Поток запроса

```mermaid
sequenceDiagram
    participant UI as SPA
    participant API as FastAPI
    participant AN as AnalyticsService
    participant DB as SQLite

    UI->>API: GET /api/customers?horizon_days=30
    API->>AN: customer_risk(horizon_days)
    AN->>DB: SELECT accounts/services/transactions
    AN->>AN: score_service() × N, агрегация по клиенту
    AN-->>API: CustomerRisk[]
    API->>API: _euro_fields() — добавить *_eur
    API-->>UI: JSON
```

## Ключевые решения

| Решение | Причина | Альтернатива отклонена |
|---|---|---|
| SQLite как хранилище по умолчанию | нулевая настройка, запуск одной командой | PostgreSQL требует внешнего сервиса |
| Целые евроценты внутри | нет ошибок округления float | Decimal везде — избыточно |
| Евро на границе API | одна точка конвертации | конвертация в моделях → риск двойной |
| `UTCDateTime` TypeDecorator | SQLite теряет tz | сравнение naive/aware ломается |
| Ленивые свойства `Settings` | тесты и env без перезагрузки модулей | dataclass с полями замораживал пути |
| Замена таблиц вместо upsert | простая идемпотентность | upsert усложняет и риск дублей |
| `reference_at` из данных | воспроизводимость | системные часы дают разные ответы |

## Зависимости

```
fastapi          веб-фреймворк
uvicorn          ASGI-сервер
sqlalchemy       ORM
pydantic         схемы запросов
httpx            клиент для тестов (TestClient)
pytest           тесты
```

Внешних сервисов, брокеров и фоновых воркеров нет. Приложение stateless,
кроме файла SQLite.

## Расширение

- **Другое хранилище**: задать `AEZA_DATABASE_URL` (нужен драйвер).
- **Новые факторы риска**: добавить ключ в `DEFAULT_WEIGHTS`, функцию-фактор и
  вес в `score_service`.
- **Новый эндпоинт**: добавить функцию в `api/app.py`, схему в `schemas.py`.
