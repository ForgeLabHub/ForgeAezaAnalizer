# Aéza Analyzer

Веб-приложение для анализа риска продления услуг и выручки под риском. Стек: FastAPI, React, PostgreSQL и Docker Compose.

## Запуск

Нужны Docker и Docker Compose. Создайте .env, задайте собственный пароль базы данных и запустите приложение:

~~~powershell
Copy-Item .env.example .env
# Задайте POSTGRES_PASSWORD в .env
docker compose up --build -d
docker compose exec api python -m backend.users create analyst@example.com
~~~

Интерфейс: http://localhost:8080. API и его справка: http://localhost:8000/api/v1/docs.

## Данные и оценки

При первом запуске приложение загружает dataset/data.json: синтетический набор из 10 аккаунтов, 30 услуг и 100 транзакций. Его можно заменить через PUT /api/v1/source/snapshot.

Оценка риска — объяснимая взвешенная эвристика, а не вероятность оттока: в наборе нет размеченных исходов. Выручка под риском считается отдельно по цене ближайшего продления и оценке риска услуги.

## Проверка

~~~bash
make doctor          # окружение: инструменты, .env, порты (ничего не меняет)
make test            # backend + модуль аутентификации
make openapi-check   # спецификация API совпадает с приложением
make docs-check      # документация, ссылки, спецификации модулей
make verify          # всё перечисленное сразу
~~~

Без make: `python -m pytest backend/tests -q`, `python -m pytest tests/test_auth.py -q`,
`cd frontend && npm ci && npm run build`.

Полная матрица «утверждение → команда → CI»: `docs/verification/matrix.md`.

## Документация

Точка входа — **[docs/index.md](docs/index.md)** (карта всех документов).

- [Сборка с чистой машины](BUILD.md) — закреплённые версии, уровни A–E
- [Запуск и обновление](docs/DEPLOYMENT_PART_B.md) · [Устройство и расчёты](docs/PROJECT_GUIDE.md)
- [Схема и миграции](docs/database/schema.md) · [API](docs/api/conventions.md)
- [Спецификации модулей](docs/modules/) · [Эксплуатация](docs/operations/monitoring.md)
- [Матрица проверок](docs/verification/matrix.md) · [Аудит переносимости](docs/audit/portability-audit-2026-10-29.md)
