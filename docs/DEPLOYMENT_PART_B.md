# Развёртывание

## Запуск

Нужны Docker и Docker Compose. В корне проекта создайте .env из образца и задайте POSTGRES_PASSWORD:

~~~bash
cp .env.example .env
docker compose up --build -d
docker compose exec api python -m backend.users create analyst@example.com
~~~

Откройте интерфейс на порту 8080, API — на 8000. Состояние: http://localhost:8000/health и /ready.

## Публичное размещение

В .env укажите адреса приложения и включите защищённые cookies:

~~~dotenv
AUTH_ISSUER=https://app.example.com
AUTH_FRONTEND_LOGIN_URL=https://app.example.com/login
AUTH_COOKIE_SECURE=true
AEZA_CORS_ORIGINS=https://app.example.com
~~~

Настройте HTTPS на reverse proxy и ограничьте публичный доступ к API согласно своей схеме сети. Секреты храните только в .env или менеджере секретов.

## Данные и обновление

При пустой PostgreSQL приложение импортирует dataset/data.json. Другой снимок можно загрузить через API; справка по схеме доступна в /api/v1/docs.

Обновление после получения новой версии:

~~~bash
docker compose up --build -d
~~~

docker compose down останавливает приложение и сохраняет данные. docker compose down -v удаляет volumes базы и учётных записей.

## Резервная копия

Скрипты сохраняют и восстанавливают PostgreSQL и SQLite:

~~~bash
./scripts/backup.sh
./scripts/restore.sh backups/<каталог>
./scripts/restore.sh backups/<каталог> --yes
~~~

Восстановление без --yes только показывает план. Проверяйте резервную копию до использования.
