# Aéza Analyzer

Приложение для анализа риска оттока и выручки под риском на синтетическом
наборе данных кейса UMIRHack 2026. Поддерживаемая версия — FastAPI API
(`backend/app/`) и React-интерфейс (`frontend/`), запускаемые через Docker Compose.

Официальный снимок находится в [`dataset/data.json`](dataset/data.json):
10 аккаунтов, 30 услуг и 100 транзакций. Это синтетический снимок, а не
история реальных клиентов. Оценка риска — объяснимая взвешенная формула,
не вероятность оттока.

## Запуск

Нужны Docker и Docker Compose. Создайте `.env`, задайте собственный пароль
PostgreSQL в `POSTGRES_PASSWORD` и запустите:

```bash
cp .env.example .env
# задайте POSTGRES_PASSWORD в .env
./run.sh
```

Интерфейс: <http://localhost:8080>. API: <http://localhost:8000>.
OpenAPI: <http://localhost:8000/api/v1/docs>.

Создайте пользователя аналитика:

```bash
docker compose exec api python -m backend.users create analyst@example.com
```

`run.sh` также принимает `status`, `logs` и `down`; по умолчанию он собирает
образы и запускает сервисы в фоне.

## Данные и расчёты

При первой загрузке пустой PostgreSQL API валидирует и импортирует
`dataset/data.json`. Импорт атомарный: некорректный снимок не заменяет
опубликованные данные. Другой снимок можно загрузить через
`PUT /api/v1/source/snapshot`.

Для сервиса формула риска:

```text
score = 100 * sum(weight_i * feature_i) / sum(weight_i)
```

В расчёт входят только доступные факторы с положительным весом; факторы
нормализуются в диапазон 0–1, а отсутствующие данные не считаются нулевым
риском. Оценка клиента равна максимальной оценке его прогнозируемых услуг.
Завершённые статусы `deleted` и `blocked` не прогнозируются.

Выручка под риском считается отдельно: цена каждого открытого платного
продления в горизонте умножается на риск услуги и учитывается один раз.
Цена не повышает риск. Деньги внутри приложения хранятся в евроцентах;
`transactions.amount` денежным полем не является.

## Метрики

После входа в интерфейс `/metrics` можно открыть напрямую в том же браузере:
<http://localhost:8000/metrics>. Endpoint выдаёт метрики Prometheus и защищён
сессионной cookie для этого пути. Для отдельного сборщика задайте
`AEZA_METRICS_TOKEN` и передавайте его в заголовке `Authorization: Bearer …`.
Подробности — в [руководстве по развёртыванию](docs/DEPLOYMENT_PART_B.md).

## Проверки

```bash
python -m pytest backend/tests/ -q
python -m pytest tests/test_auth.py -q
cd frontend
npm ci
npx tsc -b
npm run build
```

Перед запуском тестов убедитесь, что в окружении нет неожиданных `AEZA_*`
переменных. Проверка согласованности документации:

```bash
python backend/scripts/check_docs.py
```

## Документация

- [Руководство проекта](docs/PROJECT_GUIDE.md)
- [Развёртывание и Prometheus](docs/DEPLOYMENT_PART_B.md)
- [Архитектура данных](docs/DATA_ARCHITECTURE.md)
- [Авторизация](docs/AUTH_MODULE.md)
- [AI Analyst](docs/AI_ANALYST.md)
- [Агрегатный AI-ассистент](docs/AI_ASSISTANT.md)
- [Данные и их происхождение](docs/PROVENANCE_AUDIT.md)
