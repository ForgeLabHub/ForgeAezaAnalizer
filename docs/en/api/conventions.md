# API conventions

English version of [../../api/conventions.md](../../api/conventions.md).

Specification: [`backend/openapi.json`](../../../backend/openapi.json) — generated
(`make openapi`), checked in CI (`make openapi-check`). Interactive documentation runs on a
live instance: `/api/v1/docs`.

## Base rules

| Rule | Detail |
| --- | --- |
| Prefix | `/api/v1` — set in code (`backend/app/main.py`), no environment variable |
| Format | JSON |
| Authentication | Bearer JWT (`backend/auth`), cookie session for the browser |
| Time | ISO 8601 with a timezone; calculations are pinned to `AEZA_AS_OF` |
| Money | integer minor units plus a currency, never `float` |
| Errors | FastAPI `{"detail": ...}` plus domain codes from `backend/app/domain/*` |

## Key route groups

| Group | Purpose | Access |
| --- | --- | --- |
| `/auth/*` | sign-in, refresh, sign-out | — |
| `/analytics/*` | aggregates, risk, revenue at risk | analyst role |
| `/customers/*` | accounts and services | analyst role |
| `/insights/*` | AI insights | analyst role |
| `/actions/*` | suggested actions and scenarios | analyst role |
| `/source/snapshot` | snapshot ingestion | `AEZA_SOURCE_INGEST_TOKEN` |
| `/export/*` | exports | analyst role |
| `/ai/*`, `/model/*` | assistant and model state | analyst role |
| `/telegram/*` | Mini App and bot | Telegram signature |
| `/health`, `/metrics` | operations | `AEZA_METRICS_TOKEN` for metrics |

## Idempotency and limits

- Snapshot ingestion (`PUT /api/v1/source/snapshot`) is a replacement: repeating the same
  body gives the same result.
- Size and timeout limits — `AEZA_AI_TIMEOUT_SECONDS`, `AEZA_OLLAMA_TIMEOUT_SECONDS`,
  upload limits in `backend/app/api/routes_source.py`.
- Application-level rate limiting is not implemented: rely on a proxy or gateway. That is a
  known limitation, not an oversight — see
  [operations/deployment.md](../operations/deployment.md).

## Errors

| Code | Meaning |
| --- | --- |
| 400 | invalid input (domain `InvalidInput`) |
| 401 | missing or expired token |
| 403 | no role or no access to the object |
| 404 | the object does not exist |
| 409 | conflict (`ConflictError`, for example a repeated action) |
| 422 | request schema error |
| 503 | the analytics domain is unavailable (`UnavailableAnalytics`) — an honest refusal, not empty data |

## How to change the API

1. Change the route or schema; 2. `make openapi`; 3. update the client in `frontend/src`;
4. `python backend/scripts/check_docs.py` (documentation mentions only existing routes);
5. `make verify`.
