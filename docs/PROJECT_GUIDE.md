# Руководство проекта

Актуальный справочник для приложения из текущего checkout `main`. Запуск полного стека и короткий обзор находятся в корневом [README](../README.md).

## Состав

| Путь | Назначение |
| --- | --- |
| `main.py`, `backend/app/main.py` | FastAPI-приложение и HTTP-слой |
| `core.py` | Приём снимка, расчёт и публикация поколения результатов |
| `backend/app/domain/` | Валидация, риск, выручка, рекомендации и настройки |
| `backend/app/storage.py`, `backend/app/db.py` | SQLAlchemy-хранилище PostgreSQL |
| `backend/auth/` | Пользователи в SQLite, проверка паролей и RS256 access tokens |
| `backend/app/ai/` | Необязательные локальные AI-интерфейсы |
| `frontend/src/` | React + TypeScript SPA |
| `backend/migrations/`, `db/` | Схема и seed PostgreSQL |
| `dataset/data.json` | Синтетический пример входного снимка |

Compose запускает PostgreSQL 16, API и nginx для интерфейса. Аналитические данные и расчёты хранятся в PostgreSQL. Пользователей и серверные сессии создаёт и хранит модуль `backend/auth` в отдельной SQLite. Первый пользователь добавляется вручную командой `docker compose exec api python -m backend.users create <login>`. Auth SQLite и RSA-ключ сохраняются в именованном Docker volume.

## Поток данных

Снимок с массивами `accounts`, `services` и `transactions` целиком валидируется до записи. `services.ownerId` ссылается на `accounts.id`, `transactions.serviceId` — на `services.id`. После расчёта `Core` публикует новую generation, связанную с версиями источника и настроек модели. При ошибке обновления предыдущая опубликованная версия остаётся доступной.

Compose загружает `db/analytics_seed.sql` только при создании пустого хранилища. Изменение seed-файла не обновляет уже созданную базу. Полный снимок можно загрузить через API `PUT /api/v1/source/snapshot` или скрипт `backend/scripts/load_snapshot.py`.

## Риск и выручка

Score — прозрачная взвешенная оценка от 0 до 100, не вероятность оттока. Источник не содержит размеченной истории churn, поэтому нельзя заявлять точность обученной модели.

Прогноз строится для открытых услуг `active`, `suspended` и `prolong_wait`. Услуги `deleted` и `blocked` отражают уже известное состояние и исключены из будущего прогноза. Риск клиента равен максимальному score среди его прогнозируемых услуг.

Факторы: близость даты окончания, выключенное автопродление, недостаток доступных средств, `prolong_wait`, `suspended` и доля неуспешных продлений. Диагностический `failed_renewals` имеет нулевой вес, чтобы не учитывать один сигнал дважды. Отсутствующий фактор исключается из числителя и знаменателя, а не превращается в нулевой риск. Пороговые значения и веса настраиваются в приложении.

Деньги внутри расчёта представлены целыми евроцентами. `balance`, `withdrawBalance`, `bonusBalance`, `totalReplenished`, `services.price` и выручка имеют разные смыслы. Для оплаты учитываются доступный баланс и разблокированный бонус; `withdrawBalance` не используется. `transactions.amount` не является денежным полем.

Выручка под риском считается независимо от score: цена каждого открытого платного продления в выбранном горизонте взвешивается риском услуги и учитывается один раз. Цена не повышает риск. По умолчанию используется закреплённое время `AEZA_AS_OF=2026-10-19T15:00:00+00:00`; значение `now` включает периодический пересчёт и делает ответы зависимыми от времени запуска.

## API

Префикс: `/api/v1`. Текущие схемы запросов и ответов доступны в `/api/v1/docs` и `/api/v1/openapi.json`.

| Назначение | Основные маршруты |
| --- | --- |
| Авторизация | `POST /auth/login`, `GET /auth/me`, `POST /auth/refresh`, `POST /auth/logout` |
| Аналитика | `GET /analytics/summary`, `GET /analytics/events`, `GET /priority`, `GET /quality` |
| Клиенты | `GET /customers`, `GET /customers/{id}`, `GET/PATCH /customers/{id}/recommendations` |
| Модель | `GET/PATCH /model/settings`, `POST /model/settings/reset` |
| Источник | `GET/PUT /source/snapshot`, `GET /source/observations` |
| Действия | `GET/POST /actions`, `PATCH /actions/{id}` |
| Сценарии и экспорт | `POST /scenarios/compare`, `GET /export/customers.csv` |
| AI | `/ai/*` и `POST /insights/ai`; выключены по умолчанию |

К приватным маршрутам передаётся `Authorization: Bearer <token>`. `/health`, `/ready` и документация OpenAPI открыты. `/metrics` возвращает метрики Prometheus: готовность и generation анализа, число клиентов и услуг, выручку под риском, запросы API и длительность ответов. Endpoint требует `AEZA_METRICS_TOKEN` либо access token аналитика; без авторизации ответ — `401`. Инструкция с командами находится в [руководстве по развёртыванию](DEPLOYMENT_PART_B.md#6-наблюдаемость). CSV экспорт постраничный, сообщает отфильтрованное число строк и закрепляется за одной generation.

## Настройки и безопасность

Основные переменные описаны в `.env.example`. Python-приложение само не загружает `.env`; Compose загружает файл автоматически.

- В production задайте `AUTH_ISSUER` на публичный HTTPS origin и включите `AUTH_COOKIE_SECURE=true`.
- Ограничьте `AEZA_CORS_ORIGINS` реальным origin интерфейса.
- Не коммитьте `.env`, токены, базы и резервные копии.
- Для публикации используйте HTTPS через reverse proxy и проверенное резервное копирование PostgreSQL.
- AI Analyst и агрегатный AI выключены по умолчанию; подробная настройка — в [AI справке](AI_ANALYST.md) и [справке агрегатного ассистента](AI_ASSISTANT.md).

Compose сохраняет PostgreSQL и auth SQLite с ключом в именованных volumes `pg_data` и `auth_data`. Для production задайте `AUTH_ISSUER` и `AUTH_FRONTEND_LOGIN_URL` на HTTPS origin и `AUTH_COOKIE_SECURE=true`; при HTTPS и выключенном secure-cookie приложение не запустится. Команда `docker compose down` сохраняет тома, `docker compose down -v` удаляет их.

## Проверки

```powershell
python -m pytest backend/tests/ -q
python -m pytest tests/ -q
cd frontend
npm ci
npm run build
cd ..
python backend/scripts/check_docs.py
```

Frontend не имеет настроенного test runner; сборка TypeScript не заменяет ручную проверку интерфейса. Перед тестами проверьте унаследованные переменные `AEZA_*`.

## Границы и текущее окружение

Исходный набор синтетический и малый. Выручка под риском — оценка экспозиции, а не гарантированная потеря. Нагрузочный профиль и показатели стенда нужно измерять на целевом окружении.

По состоянию на 24.10.2026 публичный адрес — <https://aeza-sentinel.pixel-minds.ru/>; проверенная схема стенда содержала 18 API-путей. Возможности локального кода не следует считать развернутыми, пока они не подтверждены OpenAPI и проверкой самого стенда.
