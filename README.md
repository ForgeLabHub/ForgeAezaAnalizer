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

~~~powershell
python -m pytest backend/tests/ -q
python -m pytest tests/test_auth.py -q
cd frontend
npm ci
npm run build
~~~

## Документация

[Запуск и обновление](docs/DEPLOYMENT_PART_B.md) · [Устройство и расчёты](docs/PROJECT_GUIDE.md) · [Все инструкции](docs/README.md)
