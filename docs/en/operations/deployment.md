# Deployment

English version of [../../operations/deployment.md](../../operations/deployment.md).

The main path is Docker Compose (`docker-compose.yml`, the `./run.sh` helper or
`make compose-up`). Detailed upgrade and backup steps are in the existing
[DEPLOYMENT_PART_B.md](../DEPLOYMENT_PART_B.md); this page is a checklist.

## Procedure

```bash
cp .env.example .env
# mandatory: POSTGRES_PASSWORD (compose deliberately fails without it)
make doctor
make compose-up
make smoke-test API_URL=http://localhost:8000
make create-user EMAIL=analyst@example.com
```

UI: `http://localhost:8080`, API: `http://localhost:8000/api/v1/docs`.

## Decisions required before production

1. **Secrets.** `POSTGRES_PASSWORD`, `AUTH_PRIVATE_KEY` (JWT), `AEZA_SOURCE_INGEST_TOKEN`,
   `AEZA_METRICS_TOKEN`, `AEZA_TELEGRAM_WEBHOOK_SECRET`. None has a production-grade
   default.
2. **Fail closed.** Compose requires `POSTGRES_PASSWORD` (`:?`) — checked by a dedicated CI
   job. Do not weaken this protection.
3. **TLS.** `AUTH_COOKIE_SECURE=true` and HTTPS termination at the proxy.
4. **CORS.** `AEZA_CORS_ORIGINS` — an explicit list, not `*`.
5. **Backups.** Two databases mean two backups: PostgreSQL and SQLite (`AUTH_DATABASE`).
   `make backup` covers both; the restore check runs in CI.
6. **AI.** `AEZA_AI_ENABLED=0` by default. Enable it deliberately: it is an external call
   with a timeout up to `AEZA_AI_TIMEOUT_SECONDS` (420 s by default).

## Role separation

| Role | Ports | Access |
| --- | --- | --- |
| `web` (nginx + static) | 8080 | public |
| `api` (FastAPI) | 8000 | internal only, reached through web or a proxy |
| `db` (PostgreSQL) | 5432 | internal only |

Do not publish `api` directly: `/metrics` and service routes are protected by a token, but a
network boundary is cheaper than trusting configuration.

## After deployment

```bash
make smoke-test API_URL=http://localhost:8000
./scripts/smoke-test.sh http://localhost:8080   # through web or the proxy
```
