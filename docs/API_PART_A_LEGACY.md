# API — часть A (`aeza_analyzer/`), LEGACY

> **Устаревший документ.** Это API независимой реализации `aeza_analyzer/`
> (часть A), сохранённой в репозитории как инструмент. Канонический продукт
> (часть B, `backend/app/` + `frontend/`) имеет другой API — см.
> [`docs/PROJECT_GUIDE.md`](PROJECT_GUIDE.md). Маршруты ниже (`/api/health`, `/api/meta`,
> `/api/dashboard`, `/api/weights`, `/api/import`, `/api/audit`) в каноническом
> продукте **не существуют**. Не используйте их для демонстрации.


Базовый URL: `http://<host>:<port>`. Интерактивная документация (OpenAPI):
**`/docs`** (Swagger UI), схема — **`/openapi.json`**. Оба доступны на реально
запущенном сервере.

Денежные поля возвращаются дважды: `*_cents` (канонические целые евроценты) и
`*_eur` (строка с двумя знаками). `amount` транзакций деньгами не является.

---

## GET /api/health

Проверка живости. Тело: `{"status": "ok"}`. Коды: 200.

## GET /api/meta

Метаданные набора и последнего импорта.

```json
{
  "reference_at": "2026-10-19T14:35:53+00:00",
  "source_sha256": "10af0815…",
  "source_path": "/app/датасет.zip",
  "imported_at": "2026-10-23T18:37:16+00:00",
  "last_import": {"id": 1, "accounts": 10, "services": 30, "transactions": 100, "status": "success"},
  "default_horizon_days": 30
}
```

Коды: 200, 503 (хранилище недоступно).

## GET /api/dashboard

Сводка по данным. Параметр `horizon_days` (1–365, по умолчанию 30).

```json
{
  "counts": {"accounts": 10, "services": 30, "transactions": 100},
  "reference_at": "2026-10-19T14:35:53+00:00",
  "horizon_days": 30,
  "service_status": {"active": 6, "blocked": 6, "deleted": 6, "suspended": 6, "prolong_wait": 6},
  "risk_levels": {"low": 0, "medium": 5, "high": 3, "churned": 2, "unknown": 0},
  "revenue_at_risk_cents": 748,
  "revenue_at_risk_eur": "7.48",
  "eligible_renewal_cents": 1703,
  "eligible_renewal_eur": "17.03",
  "high_risk_customers": 3,
  "weights": {"expiry_proximity": 1.0, "autoprolong_off": 0.8, "insufficient_balance": 1.0, "failed_renewals": 0.6, "status_risk": 0.9},
  "risk_bands": [{"min": 0, "max": 34, "level": "low"}, {"min": 35, "max": 64, "level": "medium"}, {"min": 65, "max": 100, "level": "high"}]
}
```

Коды: 200, 422 (неверный `horizon_days`).

## GET /api/customers

Список клиентов с риском и экспозицией.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `horizon_days` | int 1–365 | 30 | горизонт прогноза |
| `search` | str | — | подстрока в email (без учёта регистра) |
| `level` | str | — | фильтр: `low`/`medium`/`high`/`churned`/`unknown` |
| `sort` | str | `risk_score` | `risk_score`, `revenue_at_risk_cents`, `balance_cents`, `account_id`, `service_count` |
| `order` | str | `desc` | `asc` или `desc` |

```json
{
  "total": 10,
  "items": [{
    "account_id": 7, "email": "user-0007@example.test",
    "balance_cents": 54987, "balance_eur": "549.87",
    "withdraw_balance_cents": 14446, "withdraw_balance_eur": "144.46",
    "bonus_balance_cents": 9654, "bonus_balance_eur": "96.54",
    "bonus_state": "locked",
    "total_replenished_cents": 290501, "total_replenished_eur": "2905.01",
    "service_count": 3, "live_service_count": 3,
    "risk_score": 76.74, "risk_level": "high", "confidence": 1.0,
    "revenue_at_risk_cents": 0, "revenue_at_risk_eur": "0.00",
    "eligible_renewal_cents": 0, "eligible_renewal_eur": "0.00",
    "reasons": ["highest-risk service 'service-0027' scored 77/100"]
  }]
}
```

Коды: 200, 400 (недопустимый `sort`), 422.

## GET /api/customers/{account_id}

Карточка клиента с услугами и факторами. Параметр `horizon_days`.

Дополнительно к элементу списка: `services[]` с `factors[]`:

```json
{
  "service_id": 27, "service_name": "service-0027", "status": "blocked",
  "price_cents": 474, "price_eur": "4.74",
  "expires_at": "2026-10-17T15:00:00+00:00",
  "score": 76.74, "level": "high", "confidence": 1.0,
  "reasons": ["Service is close to expiry (service already expired at snapshot time)"],
  "factors": [
    {"key": "expiry_proximity", "title": "Service is close to expiry",
     "value": 1.0, "weight": 1.0, "weighted": 1.0, "unknown": false,
     "detail": "service already expired at snapshot time"}
  ]
}
```

`value: null` + `unknown: true` означает отсутствие данных для фактора.

Коды: 200, 404 (нет аккаунта), 422.

## GET /api/services

Услуги со скорингом, отсортированы по убыванию риска.
Параметры: `horizon_days`, `status`. Коды: 200, 422.

## GET /api/weights

```json
{"weights": {...}, "defaults": {...}, "factors": {"expiry_proximity": "Service is close to expiry", ...}}
```

## PUT /api/weights

Тело: `{"weights": {"status_risk": 0.5}}` — частичное или полное переопределение.
**Побочный эффект:** немедленно влияет на все аналитические эндпоинты.

Коды: 200, 400 (неизвестный ключ / не число / отрицательное / сумма ≤ 0), 422.

## POST /api/weights/reset

Сброс к весам по умолчанию. Тело не требуется. Коды: 200.

## POST /api/import

Повторный импорт. Тело (опционально):
`{"source": "/path/to/archive.zip", "horizon_days": 30}`.

**Побочные эффекты:** заменяет таблицы `accounts`/`services`/`transactions`
целиком в одной транзакции. Идемпотентно. При отклонённых строках импорт
прерывается и данные не меняются.

Коды: 200, 400 (архив не найден / повреждён / отклонённые строки), 422.

## GET /api/audit

Воспроизводимый профиль хранилища: счётчики, уникальность, пропуски,
распределения, диапазоны, целостность. Коды: 200, 503.

## GET /

Отдаёт SPA (`static/index.html`). Статика — `/static/*`.

---

## Общие коды ошибок

| Код | Когда |
|---|---|
| 400 | некорректный запрос (веса, `sort`, импорт) |
| 404 | ресурс не найден (аккаунт) |
| 422 | ошибка валидации параметров (Pydantic) |
| 503 | хранилище недоступно/повреждено |

Тело ошибки: `{"detail": "..."}`.

## Ограничения

- **Аутентификации нет.** Любой, кто имеет сетевой доступ, может менять веса и
  запускать импорт. Для публичного развёртывания требуется обратный прокси с
  авторизацией — см. [`docs/AUTH_MODULE.md`](AUTH_MODULE.md).
- CORS не настроен: SPA обслуживается тем же origin.
