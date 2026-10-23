# Соответствие схемы источника внутренней модели

Как исходный `data.json` (и SQL-схема организатора) отображается на схему
приложения. Столбцы сохранены **1:1** (включая camelCase), чтобы соответствие
было проверяемым.

---

## 1. `accounts`

| Источник (`data.json`) | Тип источника | Приложение (`models.Account`) | Примечание |
|------------------------|---------------|-------------------------------|------------|
| `id` | int ≥ 1 | `id BIGINT PK` | без изменений |
| `email` | string, уникальный | `email TEXT UNIQUE NOT NULL` | без изменений |
| `balance` | int ≥ 0, евроценты | `balance BIGINT NOT NULL` | евроценты |
| `withdrawBalance` | int ≥ 0, евроценты | `withdrawBalance BIGINT NOT NULL` | доступно к расходованию |
| `totalReplenished` | int ≥ 0, евроценты | `totalReplenished BIGINT NOT NULL` | исторические пополнения |
| `bonusBalance` | int ≥ 0, евроценты | `bonusBalance BIGINT NOT NULL` | бонусный баланс |
| `bonusState` | `locked` \| `unlocked` | `bonusState VARCHAR(16) CHECK` | без изменений |

CHECK-ограничения повторяют DDL организатора (неотрицательность, домен
`bonusState`).

## 2. `services`

| Источник | Тип источника | Приложение (`models.Service`) | Примечание |
|----------|---------------|-------------------------------|------------|
| `id` | int ≥ 1 | `id BIGINT PK` | без изменений |
| `name` | `^[A-Za-z0-9-]+$` | `name TEXT NOT NULL` | валидация в импортёре |
| `ownerId` | int → accounts.id | `ownerId BIGINT FK → accounts.id` | RESTRICT |
| `paymentTerm` | hour/week/month/quarter_year/half_year/year | `paymentTerm VARCHAR(16) CHECK` | без изменений |
| `autoProlong` | bool | `autoProlong BOOLEAN` | без изменений |
| `createdAt` | ISO-8601 UTC `...Z` | `createdAt UTCDateTime` | нормализация в UTC |
| `expiresAt` | ISO-8601 UTC `...Z` | `expiresAt UTCDateTime` | CHECK `expiresAt ≥ createdAt` |
| `status` | active/blocked/deleted/suspended/prolong_wait | `status VARCHAR(16) CHECK` | без изменений |
| `price` | int ≥ 0, евроценты | `price BIGINT NOT NULL` | евроценты |

## 3. `transactions`

| Источник | Тип источника | Приложение (`models.Transaction`) | Примечание |
|----------|---------------|-----------------------------------|------------|
| `id` | int ≥ 1 | `id BIGINT PK` | без изменений |
| `amount` | int 0…1000 | `amount INTEGER CHECK (0..1000)` | **не конвертируется в евро** |
| `status` | performed/not_performed | `status VARCHAR(16) CHECK` | без изменений |
| `performedAt` | ISO UTC или null | `performedAt UTCDateTime NULL` | согласовано со статусом |
| `createdAt` | ISO-8601 UTC | `createdAt UTCDateTime` | без изменений |
| `type` | order/prolong | `type VARCHAR(16) CHECK` | без изменений |
| `serviceId` | int → services.id | `serviceId BIGINT FK → services.id` | RESTRICT |

---

## 4. Добавленные таблицы (не из источника)

| Таблица | Назначение |
|---------|------------|
| `risk_weights` | редактируемые веса модели риска (key → weight) |
| `import_runs` | аудит запусков импорта (sha256, количества, статус) |
| `meta` | ключ/значение: `reference_at`, `source_sha256`, `source_path`, `imported_at` |

## 5. Преобразования при импорте

1. **Идентификаторы** — без изменений (совпадают с источником).
2. **Даты** — парсинг строгого формата `YYYY-MM-DDTHH:MM:SS.mmmZ` и перевод в
   UTC. Наивные метки времени **отклоняются**, а не додумываются.
3. **Деньги** — остаются целыми евроцентами; в евро переводятся только на
   границе API (`*_eur`).
4. **Ссылочная целостность** — проверяется до записи (`ownerId`, `serviceId`);
   нарушение → строка отклоняется с причиной.
5. **Отклонённые строки** — никогда не отбрасываются молча: попадают в отчёт
   импорта, а при `strict=True` прерывают импорт целиком.

## 6. Поля из контекста кейса — проверка фактического наличия

| Ожидалось в кейсе | Есть в данных? | Где |
|-------------------|----------------|-----|
| `balance`, `withdrawBalance`, `bonusBalance`, `bonusState`, `totalReplenished` | да | `accounts` |
| `price`, `autoprolong`, `paymentTerm`, `name`, `status`, `expiresAt` | да | `services` (поле называется `autoProlong`) |
| `status`, `type`, `amount` | да | `transactions` |
| статусы `active`, `suspended`, `prolong_wait`, `deleted`, `blocked` | да | `services.status` |
| статусы транзакций `performed`, `not_performed`, типы `prolong`, `order` | да | `transactions.status` / `transactions.type` |

Все перечисленные в кейсе поля и статусы **присутствуют**; выдуманных полей
нет.
