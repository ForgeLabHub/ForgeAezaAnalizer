# Словарь данных

Описание полей источника (`data.json` из `датасет.zip`), их типов, единиц и
связей. Схема приложения повторяет источник 1:1 (см.
[`SCHEMA_MAPPING.md`](SCHEMA_MAPPING.md)).

## Денежные единицы

**Канонический формат — целые евроценты.** Правило кейса: 100 единиц = €1.
В README организатора указано, что денежные поля аккаунта и `price` хранятся
в евроцентах. Евро добавляются только на границе API как поля `*_eur`.

| Поле | Единица | Конвертируется? |
|---|---|---|
| `accounts.balance` | евроценты | да |
| `accounts.withdrawBalance` | евроценты | да |
| `accounts.totalReplenished` | евроценты | да |
| `accounts.bonusBalance` | евроценты | да |
| `services.price` | евроценты | да |
| `transactions.amount` | **не деньги** | **нет** |

`transactions.amount` генерируется независимо от `price` (README организатора)
и ограничен 0–1000. В финансовых расчётах не используется.

## accounts

| Поле | Тип | Ограничение | Смысл |
|---|---|---|---|
| `id` | int | ≥ 1, PK | идентификатор |
| `email` | str | уникальный | логин |
| `balance` | int | ≥ 0 | общий баланс, евроценты |
| `withdrawBalance` | int | ≥ 0 | доступно к расходованию, евроценты |
| `totalReplenished` | int | ≥ 0 | сумма пополнений, евроценты |
| `bonusBalance` | int | ≥ 0 | бонусный баланс, евроценты |
| `bonusState` | str | `locked` \| `unlocked` | состояние бонусов |

В наборе: `withdrawBalance ≤ balance` и `totalReplenished ≥ balance`. Это
бизнес-наблюдения, не закреплённые в схеме (README организатора).

## services

| Поле | Тип | Ограничение | Смысл |
|---|---|---|---|
| `id` | int | ≥ 1, PK | идентификатор |
| `name` | str | `^[A-Za-z0-9-]+$` | имя услуги |
| `ownerId` | int | FK → accounts.id | владелец |
| `paymentTerm` | str | см. ниже | оплаченный период |
| `autoProlong` | bool | — | автопродление |
| `createdAt` | ISO-8601 UTC | ≤ `expiresAt` | создание |
| `expiresAt` | ISO-8601 UTC | ≥ `createdAt` | окончание |
| `status` | str | см. ниже | состояние |
| `price` | int | ≥ 0, евроценты | цена периода |

**`paymentTerm`:** `hour`, `week`, `month`, `quarter_year`, `half_year`, `year`.

**`status`:**

| Значение | Трактовка в модели |
|---|---|
| `active` | живая услуга, риск 0 по статусу |
| `prolong_wait` | живая, ожидает продления (0.6) |
| `suspended` | живая, приостановлена (0.9) |
| `blocked` | живая, заблокирована (1.0) |
| `deleted` | **уже состоявшийся отток** — вне прогноза |

## transactions

| Поле | Тип | Ограничение | Смысл |
|---|---|---|---|
| `id` | int | ≥ 1, PK | идентификатор |
| `amount` | int | 0…1000 | **не деньги** |
| `status` | str | `performed` \| `not_performed` | результат |
| `performedAt` | ISO UTC / null | см. ниже | время выполнения |
| `createdAt` | ISO UTC | — | создание |
| `type` | str | `order` \| `prolong` | тип |
| `serviceId` | int | FK → services.id | услуга |

Инвариант: `not_performed` ⇒ `performedAt = NULL`;
`performed` ⇒ `performedAt ≥ createdAt`.

## Связи

```
accounts 1 ──── N services 1 ──── N transactions
```

Оба FK — `ON DELETE RESTRICT`, `ON UPDATE RESTRICT` (история не удаляется
каскадно).

## Служебные таблицы приложения

| Таблица | Назначение |
|---|---|
| `risk_weights` | редактируемые веса модели (`key`, `weight`) |
| `import_runs` | журнал импортов: sha256, счётчики, статус, время |
| `meta` | `reference_at`, `source_sha256`, `source_path`, `imported_at` |

## Фактический профиль набора

| Метрика | Значение |
|---|---|
| accounts / services / transactions | 10 / 30 / 100 |
| уникальные id | 10 / 30 / 100 |
| дубликаты | нет |
| пропуски | нет |
| `deleted`-услуг | 6 |
| услуг с `expiresAt` до снимка | **17 из 30** |
| диапазон `createdAt` | 2025-09-14 … 2026-10-19 |
| `reference_at` | `2026-10-19T14:35:53Z` |

Подробный профиль: [`IMPORT_AND_DATA_AUDIT.md`](IMPORT_AND_DATA_AUDIT.md).
