# Aéza Analyzer

Приложение для анализа риска оттока и выручки под риском по снимку данных Aéza. Основной стек: FastAPI, PostgreSQL, React и TypeScript. Данные набора синтетические: 10 аккаунтов, 30 услуг и 100 транзакций.

## Быстрый запуск

Нужны Docker и Docker Compose. Создайте `.env`. Для production до запуска задайте `AUTH_ISSUER` и `AUTH_FRONTEND_LOGIN_URL` на HTTPS-домен приложения, `AUTH_COOKIE_SECURE=true` и точный `AEZA_CORS_ORIGINS`.

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

HTTP-порты контейнеров доступны только через loopback, чтобы внешний reverse proxy завершал TLS до передачи запросов приложению.

Создайте учётную запись отдельно; приложение не заводит администратора при старте:

```powershell
docker compose exec api python -m backend.users create analyst@example.com
```

Команда запросит пароль дважды. Пользователи хранятся в `db/auth.sqlite3` в постоянном Docker volume; ключ RS256 сохраняется рядом. Интерфейс: <http://localhost:8080>. API: <http://localhost:8000>. Swagger: <http://localhost:8000/api/v1/docs>.

## Важное

- Риск — объяснимый rule-based score, а не вероятность оттока или обученная ML-модель.
- `deleted` и `blocked` не прогнозируются как будущий отток; риск клиента — максимум по открытым услугам.
- Денежные значения хранятся в евроцентах. `transactions.amount` не является суммой платежа.
- Опорное время по умолчанию закреплено на `2026-10-19T15:00:00Z`.
- `docker compose down` сохраняет данные. Не применяйте `down -v`, если нужно сохранить базы.

Проверки: `python -m pytest backend/tests/ -q`, `python -m pytest tests/ -q`, `cd frontend; npm ci; npm run build`.

Архитектура, API, модель данных, настройки и эксплуатационные ограничения собраны в [руководстве проекта](docs/PROJECT_GUIDE.md). Специализированные справки и архивные материалы перечислены в [документации](docs/README.md).
