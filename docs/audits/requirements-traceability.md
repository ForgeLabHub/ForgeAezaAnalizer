# Матрица соответствия ТЗ

Дата: 2026-10-24. Ветка `feat/deployment-readiness`.
Среда проверки: локальный `TestClient` на SQLite, официальный `dataset/data.json`,
`as_of = 2026-10-19T15:00:00+00:00`, движок `aeza-heuristic-1.3.0`.

Статусы: `PASS` — подтверждено запуском; `PARTIAL` — работает частично;
`FAIL` — не работает; `NOT VERIFIED` — нет доказательств.

Скрипт проверки: воспроизводит вход, импорт снимка, сортировки, карточку,
настройки, метрики, экспорт и выход. Команда:

```bash
.venv/bin/python /tmp/acceptance.py     # 26 проверок, 1 заведомо строгая (см. R-9)
```

---

## Сводка

| ID | Требование | Статус | Доказательство |
| --- | --- | --- | --- |
| R-1 | Запуск по README | PASS | `create_app()` поднимается, `/health` 200 |
| R-2 | Загрузка набора организатора | PASS | `PUT /source/snapshot` → 200; 10/30/100 |
| R-3 | Динамический расчёт, не хардкод | PASS | смена веса меняет score (см. R-9) |
| R-4 | Список: score, уровень, причины, недостаток данных | PASS | `byCategory` содержит `not_applicable`=4 |
| R-5 | Сортировка ID/email/balance/totalReplenished, обе стороны | PASS | 10 комбинаций → 200 |
| R-6 | Карточка клиента: услуги и признаки риска | PASS | клиент 10: 3 услуги, 3 причины |
| R-7 | GET и PATCH коэффициентов | PASS | 200; отрицательный вес → 422 |
| R-8 | Сохранение настроек после перезапуска | PASS | тесты `test_api`/`test_integration` |
| R-9 | Пересчёт после смены коэффициента | PASS | score 71.4→81.8, выручка 5.80→7.72 € |
| R-10 | Пересчёт после замены снимка | PASS | generation растёт; сводка меняется |
| R-11 | Денежная оценка и её объяснение | PASS | 580 центов = €5.80; формула в `revenue.py` |
| R-12 | `/metrics` с актуальными агрегатами | PASS | 200; риск-категории; без email |
| R-13 | Авторизация и защита API | PASS | приватные маршруты → 401 |
| R-14 | login / me / logout | PASS | 200 / 200 / 204 |
| R-15 | Swagger и OpenAPI | PASS | `/api/v1/docs` 200, `/openapi.json` 200 |
| R-16 | Docker Compose | PASS | стек собран и запущен (см. отчёт §I) |
| R-17 | Обязательный комментарий | PASS | `backend/app/domain/money.py:3` |
| R-18 | Полный демо-сценарий | PASS | локально пройден; на стенде — PARTIAL |

### Добавлено в итерации 2026-10-24

| ID | Требование | Статус | Доказательство |
| --- | --- | --- | --- |
| R-19 | Ограничение частоты попыток входа | PASS | 10×401 → **429** + `Retry-After`; `test_security_hardening.py` |
| R-20 | Безопасное значение по умолчанию `AEZA_ALLOW_DEV_SECRET` | PASS | `Settings()` без секрета → `ValueError`; тесты в `test_security_hardening.py` |
| R-21 | CORS не `*` по умолчанию | PARTIAL | исправлено в `docker-compose.yml`; стенд требует переразвёртывания |
| R-22 | Runtime-БД не отслеживается Git | PASS | `db/auth.sqlite3` убран из индекса, добавлен в `.gitignore` |
| R-23 | Контрольные расчёты воспроизводятся | PASS | клиент №10 = **71.4**, `revenueAtRisk` = **5.80 €** через `module.create()` |
| R-24 | Frontend собран без изменения дизайна | PASS | `npm run build` exit 0; `docs/audits/frontend-preservation.md` |
| R-25 | Документация соответствует коду | PASS | README/ARCHITECTURE/DATA_AND_RISK_MODEL/SECURITY/TESTING обновлены |

---

## Детали

### R-1. Запуск
`create_app(settings, analytics)` поднимает приложение; `GET /health` → 200,
`GET /ready` → 200. `GET /api/v1/docs` → 200.

### R-2. Набор организатора
`dataset/data.json`: `accounts` 10, `services` 30, `transactions` 100.
Emails — `user-0001@example.test` … `user-0010@example.test`.
`PUT /api/v1/source/snapshot` → **200**. После импорта сводка: 10 клиентов.

### R-3, R-9. Динамический расчёт и пересчёт по весу
Изменение `expiry_proximity` 3.0 → 9.0 через `PATCH /api/v1/model/settings`
(ответ 200) даёт:

| Клиент | До | После |
| --- | --- | --- |
| 1 | 38.4 medium | 57.9 medium |
| 4 | 35.4 medium | 51.1 medium |
| 5 | 71.4 high | 81.8 high |
| 9 | 65.4 high | 76.3 high |
| 10 | 71.4 high | 81.8 high |

Выручка под риском: **5.80 € → 7.72 €**. `generation` 2 → 3.
Показатели вычисляются, а не захардкожены.

Оговорка: `byCategory` остался `{low 0, medium 3, high 3, not_applicable 4}` —
на официальном наборе изменение веса не переводит никого через порог, потому
что все сработавшие факторы есть и у «medium», и у «high» клиентов. Смена
категории видна на расширенном наборе (60 клиентов).

### R-4. Список клиентов
Ответ `GET /api/v1/customers` содержит `riskScore`, `riskCategory`,
`topReasons`, `missingData`. `byCategory` включает `not_applicable` (4) — это
уже завершённые услуги, они не оцениваются прогнозом, а не получают ложный
низкий риск. Отдельная категория `insufficient_data` существует и пуста на
этом наборе (не подменяется нулём).

### R-5. Сортировка
Проверены `id`, `email`, `riskScore`, `balance`, `totalReplenished` ×
`asc`/`desc` — 10 запросов, все **200**. Порядок стабилен: при равенстве
значений вторичный ключ — `customer_id` (см. `storage.customers`).

### R-6. Карточка клиента
`GET /api/v1/customers/10` → `riskScore` **71.4**, `riskCategory` `high`,
3 услуги, 3 причины, 2 рекомендации. Совпадает с контрольным значением.

### R-7, R-8. Настройки
`GET /api/v1/model/settings` → 200. `PATCH` с корректными весами → 200 и
новое поколение. `PATCH` с `expiry_proximity = -1` → **422** (отклонено).
`POST /api/v1/model/settings/reset` → 200. Сохранение после перезапуска
покрыто тестами `backend/tests/test_api.py` и `test_integration.py`.

### R-10. Замена снимка
`PUT /api/v1/source/snapshot` публикует новое поколение; сводка и score
пересчитываются. Атомарность и откат при некорректном снимке покрыты
`test_integration.py` (отклонённый импорт не меняет предыдущие 10/30/100).

### R-11. Денежная оценка
`revenueAtRisk` официального набора: **580 центов = 5.80 €**
(`revenue.revenueAtRiskEur == "5.80"`). Внутри — целые евроценты; наружу
добавляется `eur`-строка. Формула и период описаны в
`docs/audits/calculation-audit.md`.

### R-12. Метрики
`GET /metrics` → 200. Метрики: `aeza_analysis_ready`,
`aeza_analysis_generation`, `aeza_customers_total`, `aeza_services_total`,
`aeza_services_open_total`, `aeza_revenue_at_risk_eur`,
`aeza_upcoming_renewals_eur`, `aeza_customers_by_risk_category{category}`,
`aeza_analysis_calculated_timestamp_seconds`, а также
`aeza_api_requests_total` и `aeza_api_duration_seconds`.
В теле **нет** символа `@` — email в labels не попадают.
На стенде `/metrics` отвечает **401** без токена.

### R-13, R-14. Авторизация
`GET /api/v1/customers` без токена → **401**. Неверный пароль → 401.
`POST /api/v1/auth/login` → 200 с `access_token`;
`GET /api/v1/auth/me` → 200; `POST /api/v1/auth/logout` → 204.

### R-15. OpenAPI
`/api/v1/openapi.json` → 200, title `Aéza Analyzer`, version `2.0.0`.
Экспортируемая копия — `backend/openapi.json`.

### R-16. Docker Compose
Стек (db + api + web) собран и запущен; все три контейнера `healthy`.
Проверки и ограничения — в финальном отчёте, раздел «Деплой».

### R-17. Обязательный комментарий
`backend/app/domain/money.py`, строка 3: `Aéza - это быстрый хостинг`.

### R-18. Демонстрационный сценарий
Локально пройден полностью (вход → список → сортировки → карточка → причины →
деньги → смена веса → пересчёт → what-if → рекомендация → экспорт → метрики).
На публичном стенде сценарий **PARTIAL**: маршруты Playbooks там отсутствуют
(стенд соответствует `origin/main`).

---

## Не проверено

| Пункт | Причина |
| --- | --- |
| Автозапуск после перезагрузки ВМ | нет SSH-доступа к серверу |
| Резервное копирование и восстановление | нет SSH-доступа |
| Права на файл SQLite в production | нет SSH-доступа |
| Nginx/systemd внутри сервера | нет SSH-доступа |
| Playbooks на стенде | функциональность не развёрнута |

Команды для владельца — в `docs/audits/production-readiness-audit.md` §7.
