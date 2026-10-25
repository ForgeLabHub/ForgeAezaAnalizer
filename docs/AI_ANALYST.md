# AI Analyst

AI Analyst — необязательная функция для пояснения аналитики с помощью локальной модели Ollama. Она выключена по умолчанию и не участвует в расчёте риска.

## Включение

Установите Ollama, загрузите модель и укажите доступный из API-контейнера адрес в .env:

~~~bash
ollama pull qwen2.5:3b-instruct
~~~

~~~dotenv
AEZA_AI_ENABLED=1
AEZA_AI_PROVIDER=ollama
AEZA_AI_MODEL=qwen2.5:3b-instruct
AEZA_AI_BASE_URL=http://host.docker.internal:11434
~~~

Значение host.docker.internal подходит для Compose-конфигурации проекта. После изменения .env пересоздайте API: docker compose up -d api.

## Использование

Справка по API доступна в /api/v1/docs. Основные маршруты: GET /api/v1/ai/status, POST /api/v1/ai/chat и POST /api/v1/ai/customers/{id}/explain. Для маршрутов нужна авторизация.

Модель формулирует объяснение на основе данных приложения и не изменяет снимок или настройки. Балл риска остаётся эвристикой, а не вероятностью оттока. Другие параметры Ollama перечислены в .env.example.
