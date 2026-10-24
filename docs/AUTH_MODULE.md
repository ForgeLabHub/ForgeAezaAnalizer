# Общий модуль аутентификации (FastAPI + SQLite + OIDC)

Модуль `backend/auth/` обслуживает учётные записи и серверные сессии Compose API.
Он проверяет пароль, выпускает RS256 access token и предоставляет OIDC-маршруты
для интеграций. Пароли хранятся только в виде хешей в SQLite.

Добавлены зависимости **PyJWT и cryptography** для RS256/JWKS. SQLite, scrypt и кеш используют стандартную библиотеку Python. Фронтенд в этот модуль не входит.

## Запуск

Python 3.12+. Из корня проекта в PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.users create alice
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Команда создания пользователя запросит пароль дважды; минимум 12 символов. База `db/auth.sqlite3` и таблицы `users` и `auth_sessions` создаются автоматически из `db/schema.sql`. Для создания пустой базы: `python -m backend.users init`. В Docker Compose используйте `docker compose exec api python -m backend.users create <login>`; SQLite и RSA-ключ хранятся в томе `auth_data`. Администратор не создаётся автоматически, пароль в Compose не задаётся.

SPA использует `/api/v1/auth/login`, `/api/v1/auth/me`, `/api/v1/auth/refresh` и `/api/v1/auth/logout`. Поле `email` от интерфейса передаётся в auth-модуль как `login`; пользователи и серверные сессии хранятся в SQLite. Access token хранится только в памяти вкладки, а HttpOnly-cookie восстанавливает сессию после перезагрузки и выдаёт новый токен по истечении короткого access token. Auth-запросы проверяют заголовок `Origin`.

Открыть [API](http://localhost:8000/docs). При первом запуске автоматически создаётся RSA-ключ `db/private_key.pem`; он сохраняется между перезапусками. Базу и приватный ключ нужно хранить вне публичного доступа, с правами только для процесса приложения.

Настройки перечислены в `.env.example`. Приложение читает переменные окружения; файл `.env` автоматически не загружается. Например:

```powershell
$env:AUTH_ISSUER = "https://auth.example.com"
$env:AUTH_FRONTEND_LOGIN_URL = "https://app.example.com/login"
$env:AUTH_COOKIE_SECURE = "true"
$env:OIDC_CLIENT_ID = "website"
$env:OIDC_REDIRECT_URIS = "https://app.example.com/auth/callback"
```

В локальной разработке используйте `localhost` и на фронтенде, и для API. Cookie имеют `SameSite=Lax`: фронтенд страницы входа и сервер авторизации должны быть на одном site, например `app.example.com` и `auth.example.com`. CORS разрешён только origin страницы входа, указанной в `AUTH_FRONTEND_LOGIN_URL`.

## Вход с фронтенда

```javascript
const requestId = new URLSearchParams(location.search).get("request_id");
const response = await fetch("http://localhost:8000/auth/login", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ login, password, request_id: requestId }),
});
const result = await response.json();
if (!response.ok) throw new Error(result.error_description || "Ошибка входа");
if (result.redirect_url) location.assign(result.redirect_url);
```

Ответ содержит `access_token`, `token_type: "Bearer"`, `expires_in`, `scope` и `user: {sub, preferred_username}`. При входе в рамках OIDC-запроса также возвращается `redirect_url` с одноразовым кодом. Access token передаётся в `Authorization: Bearer …`; cookie отправляется браузером при `credentials: "include"`.

| Метод | Адрес | Назначение |
| --- | --- | --- |
| POST | `/auth/login` | JSON `{login, password, request_id?}`, проверка пароля, токен и cookie |
| GET | `/auth/me` | Данные пользователя по Bearer-токену или cookie |
| POST | `/auth/refresh` | Новый access token по действующей cookie, без повторного ввода пароля |
| POST | `/auth/logout` | Отзыв текущей сессии и удаление cookie |
| GET | `/.well-known/openid-configuration` | OIDC discovery |
| GET | `/oidc/authorize` | Authorization Code + PKCE S256 |
| POST | `/oidc/token` | Обмен кода на access token и ID token |
| GET | `/oidc/jwks` | Публичный ключ проверки подписи JWT |
| GET, POST | `/oidc/userinfo` | OIDC claims по Bearer access token |

## Подключение сайта по OIDC

Issuer по умолчанию: `http://localhost:8000`. Client ID: `website`. Зарегистрированный redirect URI: `http://localhost:3000/auth/callback`. Адрес возврата проверяется точным совпадением с одним из `OIDC_REDIRECT_URIS` через запятую.

1. Сайт генерирует криптографически случайные `state`, `nonce` и `code_verifier` длиной 43–128 символов. Хранит их в контексте текущей попытки входа.
2. Вычисляет `code_challenge = BASE64URL(SHA256(code_verifier))` без padding и направляет браузер на `/oidc/authorize` с параметрами `client_id`, `redirect_uri`, `response_type=code`, `scope=openid profile`, `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`.
3. При наличии сессии сервер сразу перенаправляет на callback сайта с `code` и исходным `state`. Без сессии перенаправляет на `AUTH_FRONTEND_LOGIN_URL?request_id=…`; фронтенд выполняет описанный выше POST `/auth/login` и переходит по `redirect_url`. Попытка входа привязана к браузеру отдельной HttpOnly cookie.
4. Сайт проверяет `state` и обменивает код через POST `/oidc/token`, Content-Type `application/x-www-form-urlencoded`:

```text
grant_type=authorization_code
client_id=website
code=<полученный код>
redirect_uri=http://localhost:3000/auth/callback
code_verifier=<исходный verifier>
```

5. OIDC-библиотека сайта проверяет подпись ID token по JWKS, `iss`, `aud`, `exp` и сохранённый `nonce`, затем создаёт сессию сайта. Самостоятельно декодировать JWT без проверки подписи недостаточно.

Для браузерного клиента `OIDC_CLIENT_SECRET` остаётся пустым: используется public client с обязательным PKCE. Для сайта с сервером задайте секрет и используйте HTTP Basic на `/oidc/token`; секрет должен быть только на сервере сайта. PKCE обязателен в обоих режимах. Поддерживаются scopes `openid`, `profile`, параметры `prompt=none`, `prompt=login`, `max_age`; refresh token и динамическая регистрация клиентов не реализованы.

`/auth/login` выдаёт access token для API. OIDC ID token сайт получает при обмене кода: для входа на сайт необходимо пройти описанный OIDC-поток.

## Кеш и сроки действия

- Пароли в SQLite представлены scrypt-хешами с уникальной солью, `N=131072, r=8, p=1`.
- Сессия живёт 8 часов в SQLite, access token — 15 минут, код — 60 секунд, попытка OIDC-входа — 5 минут. Срок токена ограничен остатком жизни сессии.
- Профиль кешируется на 30 секунд; после этого перечитывается из SQLite. `is_active=0` или изменение `auth_version` отзывают доступ при следующем обновлении профиля.
- `/auth/logout` немедленно прекращает использование токенов этой сессии на `/auth/me` и `/oidc/userinfo`. Уже выданные JWT, проверяемые сторонним сайтом автономно, действуют до своего `exp`; собственную сессию сайт завершает сам.
- Кеш ограничен 10 000 записей на тип. Коды потребляются атомарно один раз. Не более 10 попыток входа с IP за окно 60 секунд; одновременно выполняются до 4 проверок scrypt.
- Сессии сохраняются между перезапусками в SQLite; незавершённые OIDC-попытки и коды остаются в памяти процесса. Для текущего OIDC-потока используйте `--workers 1`, чтобы код и попытка входа обрабатывались одним процессом.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Проверяются вход, кеш профиля, обновление токена, отзыв сессии, подписи и сроки JWT, OIDC-переход, PKCE, одноразовое потребление кода в двух потоках, привязка к браузеру, redirect URI, клиентский секрет, scopes, CORS/Origin и ограничения попыток входа.
