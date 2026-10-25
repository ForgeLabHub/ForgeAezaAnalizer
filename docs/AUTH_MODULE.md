# Учётные записи

Пользователей приложения создаёт оператор; по умолчанию учётных записей нет. В Docker Compose создайте пользователя командой:

~~~bash
docker compose exec api python -m backend.users create analyst@example.com
~~~

Команда запросит пароль дважды. Пользователи и сессии хранятся в SQLite в volume auth_data; пароль хранится в виде хеша.

Другие команды управления:

~~~bash
docker compose exec api python -m backend.users list
docker compose exec api python -m backend.users show analyst@example.com
~~~

Интерфейс использует /api/v1/auth/login, /api/v1/auth/me, /api/v1/auth/refresh и /api/v1/auth/logout. Приватные запросы API передают access token в заголовке Authorization: Bearer <token>.

Для публичного HTTPS-развёртывания задайте AUTH_ISSUER, AUTH_FRONTEND_LOGIN_URL и AUTH_COOKIE_SECURE=true в .env.
