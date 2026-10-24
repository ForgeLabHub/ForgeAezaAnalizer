# Импорт данных

## Формат снимка

`PUT /api/v1/source/snapshot` принимает JSON-объект с тремя массивами — ровно тот
формат, что лежит в `dataset/data.json`:

```json
{
  "accounts": [
    {
      "id": 1,
      "email": "user-0001@example.test",
      "balance": 20379,
      "withdrawBalance": 7055,
      "totalReplenished": 420669,
      "bonusBalance": 5514,
      "bonusState": "unlocked"
    }
  ],
  "services": [
    {
      "id": 1,
      "name": "service-0001",
      "ownerId": 1,
      "paymentTerm": "hour",
      "autoProlong": false,
      "createdAt": "2026-01-01T00:00:00.000Z",
      "expiresAt": "2026-10-19T15:30:00.000Z",
      "status": "active",
      "price": 95
    }
  ],
  "transactions": [
    {
      "id": 1,
      "amount": 0,
      "status": "not_performed",
      "performedAt": null,
      "createdAt": "2026-10-19T14:00:00.000Z",
      "type": "prolong",
      "serviceId": 1
    }
  ]
}
```

Требуются все три ключа. Каждый массив может быть пустым — это корректный снимок.

---

## Что проверяется

Валидация выполняется **полностью до** любой записи в базу.

### Структура и типы

- все три ключа присутствуют и являются массивами;
- обязательные поля каждой записи на месте;
- типы соответствуют схеме (целые — целые, строки — строки, булевы — булевы);
- неизвестные поля не ломают импорт (игнорируются).

### Значения

| Правило | Проверка |
| --- | --- |
| Денежные поля неотрицательны | `balance`, `withdrawBalance`, `totalReplenished`, `bonusBalance`, `price` ≥ 0 |
| Предел суммы транзакции | `0 ≤ amount ≤ 1000` |
| Согласованность баланса | `withdrawBalance ≤ balance` |
| Согласованность пополнений | `totalReplenished ≥ balance` |
| Даты услуг | `expiresAt ≥ createdAt` |
| Даты транзакций | при `performed` — `performedAt ≥ createdAt`; при `not_performed` — `performedAt = null` |
| Статусы | только документированные значения (`active`, `suspended`, `prolong_wait`, `deleted`, `blocked`) |
| Типы транзакций | только `prolong` и `order` |
| Статусы транзакций | только `performed` и `not_performed` |

### Ссылочная целостность

- `services.ownerId` указывает на существующий `accounts.id`;
- `transactions.serviceId` указывает на существующий `services.id`;
- идентификаторы уникальны внутри каждой таблицы.

Дубликаты идентификаторов и висящие ссылки отклоняются: импорт не создаёт
несогласованный набор.

---

## Атомарность

Порядок операций:

1. Разбор и валидация всего снимка в памяти.
2. Единственная транзакция базы: удаление прежних строк, вставка новых.
3. При любой ошибке — откат, прежний набор сохраняется без изменений.

**Отклонённый импорт не оставляет систему в частично обновлённом состоянии.** Это
проверяется тестами: после неудачного импорта объёмы и сводная аналитика побайтово
совпадают с состоянием до попытки.

Повторный импорт того же снимка идемпотентен: результат — тот же набор данных, а не
дубликаты.

---

## Отчёт об импорте

Ответ содержит отчёт:

```json
{
  "report": {
    "status": "succeeded",
    "accepted": { "accounts": 10, "services": 30, "transactions": 100 },
    "rejected": 0,
    "duplicates": 0,
    "previous": { "accounts": 10, "services": 30, "transactions": 100 },
    "message": "snapshot applied"
  }
}
```

| Поле | Значение |
| --- | --- |
| `accepted` | Число принятых записей по таблицам |
| `rejected` | Число отклонённых записей |
| `duplicates` | Число обнаруженных дубликатов |
| `previous` | Объёмы набора до импорта |

Текущее состояние и отчёт последнего импорта доступны через
`GET /api/v1/source/snapshot`.

---

## Ошибки

| Ситуация | HTTP | Тело |
| --- | --- | --- |
| Нарушение схемы или значений | 422 | `{"detail": "Snapshot отклонён: <поле>: <причина>"}` |
| Нет или недействителен токен | 401 | `{"detail": "..."}` |
| Внутренняя ошибка записи | 500 | Откат, набор не изменён |

Пример сообщения:

```
Snapshot отклонён: transactions.0.amount: Input should be less than or equal to 1000
```

Сообщение указывает конкретное поле и причину — по нему можно исправить файл, не
читая код.

---

## Загрузка

### Через API

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"analyst@aeza.test","password":"demo123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -X PUT http://127.0.0.1:8000/api/v1/source/snapshot \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @dataset/data.json
```

### Скриптом

```bash
cd backend
python scripts/load_snapshot.py path/to/snapshot.json
```

Скрипт использует ту же валидацию и тот же атомарный импорт, что и API.

### Автоматически при старте

Compose загружает `db/analytics_seed.sql` в PostgreSQL при первом создании каталога
`db/postgres/`. Этот seed содержит официальный набор организатора и одно
опубликованное поколение расчёта; таблиц авторизации в нём нет. Для пустой БД вне Compose можно включить
`AEZA_SEED_DEMO_DATA=1`; тогда приложение возьмёт JSON из `AEZA_SNAPSHOT_PATH`.

### Через SQL

Для Compose повторно применять seed вручную не нужно. В чистую PostgreSQL базу его
можно загрузить так:

```bash
psql -X -v ON_ERROR_STOP=1 -d DATABASE_NAME \
  -f db/analytics_seed.sql
```

Seed содержит официальный набор организатора: **10 клиентов, 30 услуг, 100
транзакций** и одно поколение расчёта — те же данные, что в `dataset/data.json`,
поэтому цифры стенда совпадают с README и материалами защиты. Seed
сгенерирован скриптом `backend/scripts/export_seed.py` (см. ниже), а не
редактируется вручную.

### Перегенерация seed

Seed — это дамп аналитической базы, поэтому его не правят руками. После
изменения исходных данных:

```bash
# 1. Загрузить снимок в чистую базу (пример — SQLite во временном файле).
rm -f /tmp/seed.db
AEZA_DATABASE_URL="sqlite:////tmp/seed.db" AEZA_JWT_SECRET=x \
AEZA_ANALYTICS_FACTORY=backend.app.domain.module:create \
AEZA_AS_OF="2026-10-19T15:00:00+00:00" \
  python backend/scripts/load_snapshot.py dataset/data.json

# 2. Выгрузить её в seed (CRLF сохраняется автоматически).
python backend/scripts/export_seed.py \
  --database-url "sqlite:////tmp/seed.db" \
  --note "Official organiser snapshot (dataset/data.json): 10 accounts, 30 services, 100 transactions."

# 3. Убедиться, что дефолты seed совпадают с дефолтами кода.
cd backend && python -m pytest tests/test_domain.py -q -k seed
```

Скрипт `export_seed.py` выгружает таблицы `analyzer_*` в том же порядке и с теми
же `::json`-приведениями, что и исходный дамп, и завершает файл CRLF. Тест
`test_bundled_seed_defaults_match_code_defaults` падает, если выгруженный seed
разошёлся с `DEFAULT_WEIGHTS` — это защита от повторения расхождения 2026-10-24.

---

## Приватность

Импорт и аналитика не пишут в логи и метрики email, идентификаторы клиентов и иные
персональные данные. Метрики Prometheus агрегированы; меток с идентификаторами
клиентов нет.
