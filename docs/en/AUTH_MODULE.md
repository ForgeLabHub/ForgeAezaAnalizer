# Accounts

English version of [../AUTH_MODULE.md](../AUTH_MODULE.md).

Users are created by the operator; by default there are no accounts. In Docker Compose
create a user with:

```bash
docker compose exec api python -m backend.users create analyst@example.com
```

The command asks for the password twice. Users and sessions are stored in SQLite in the
`auth_data` volume; the password is stored as a hash.

Other management commands:

```bash
docker compose exec api python -m backend.users list
docker compose exec api python -m backend.users show analyst@example.com
```

The interface uses `/api/v1/auth/login`, `/api/v1/auth/me`, `/api/v1/auth/refresh` and
`/api/v1/auth/logout`. Private API requests carry the access token in the header
`Authorization: Bearer <token>`.

For a public HTTPS deployment set `AUTH_ISSUER`, `AUTH_FRONTEND_LOGIN_URL` and
`AUTH_COOKIE_SECURE=true` in `.env`.
