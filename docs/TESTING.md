# Testing and verification

All results below were produced by **actually running** the commands on the
current code (2026-10-24, branch `feat/deployment-readiness`). Items that were
not checked are marked explicitly.

## Test suites

| Component | Command (from the repo root) | Result |
| --- | --- | --- |
| Backend (FastAPI product) | `cd backend && python -m pytest tests/ -q` | **208 passed** |
| Root suite (part A + auth module) | `python -m pytest tests/ -q` | **69 passed** |
| Frontend typecheck | `cd frontend && npx tsc -b` | exit **0** |
| Frontend build | `cd frontend && npm run build` | exit **0** |

**Total 279 tests, all passing** (210 backend + 69 root). The backend count grew
from 201 to 210 in this iteration (7 security tests plus 2 tests added by the
parallel session's deprecated-factor change).

Environment: Python 3.13, pytest via `.venv`, Node 24, Vite 5.4.

## Backend suites by file

| File | Tests | Covers |
| --- | --- | --- |
| `test_api.py` | 45 | HTTP surface, auth, sorting, pagination, metrics, OpenAPI |
| `test_domain.py` | 44 | money, factor normalisation, thresholds, scoring |
| `test_insights.py` | 29 | scenario comparison, data quality, priority |
| `test_methodology.py` | 22 | approved methodology, horizons, windows |
| `test_module_contract.py` | 15 | analytics plug-in contract, control values |
| `test_playbooks.py` | 14 | recommendation status persistence, concurrency |
| `test_revenue.py` | 13 | revenue at risk, no double counting |
| `test_integration.py` | 13 | snapshot import, atomicity, rollback |
| `test_money_rounding.py` | 8 | single conversion, ROUND_HALF_UP |
| `test_security_hardening.py` | 7 | **new**: dev-secret default, login throttle |

## Control values (reproduced, not asserted from memory)

Run through the canonical module (`backend/app/domain/module.py:create`) on
`dataset/data.json`:

```
revenueAtRiskEur  = 5.80      (580 cents)
upcomingRenewalsEur = 17.03
byCategory = {low 0, medium 3, high 3, insufficient_data 0, not_applicable 4}
customer #10 score = 71.4 (high);  #5 = 71.4, #9 = 65.4, #1 = 38.4, #4 = 35.4, #6 = 34.6
```

Changing `expiry_proximity` 3.0 → 9.0 gives score **81.8** and revenue
**7.72 EUR**. Full transcript: `docs/audits/calculation-audit.md`.

## Live API walkthrough (local, SQLite)

Start (from the repo root):

```bash
export AEZA_JWT_SECRET=... AEZA_ADMIN_EMAIL=analyst@aeza.test \
       AEZA_ADMIN_PASSWORD=demo123 AEZA_SEED_DEMO_DATA=1 \
       AEZA_DATABASE_URL="sqlite:///$(pwd)/data/analytics.sqlite" \
       AEZA_AUTH_DATABASE_URL="sqlite:///$(pwd)/db/auth.sqlite3" \
       AEZA_ANALYTICS_FACTORY="backend.app.domain.module:create"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

> Note: the documented command is `main:app` from the repo root. Running
> `app.main:app` from `backend/` fails with `ModuleNotFoundError: core`, because
> `core.py` lives in the repo root. The README was corrected in this iteration.

| Check | Command | Result |
| --- | --- | --- |
| Health | `curl /health` | `200 {"status":"ok"}` |
| Readiness | `curl /ready` | `200 {"status":"ready"}` |
| Swagger | `curl /api/v1/docs` | `200` |
| OpenAPI | `curl /api/v1/openapi.json` | `200` |
| API protected without token | `curl /api/v1/customers` | **401** |
| Metrics without token | `curl /metrics` | **401** |
| Metrics with token | `curl /metrics -H "Authorization: Bearer ..."` | `200`, `aeza_revenue_at_risk_eur 5.8` |
| Login | `POST /api/v1/auth/login` | `200` with `access_token` |
| Login, wrong password x10 then more | `POST /api/v1/auth/login` | `401`x10 -> **`429`** with `Retry-After: 300` |
| Sorting both directions | `GET /customers?sortBy=balance&sortDir=asc\|desc` | `200`, order flips |
| Settings change | `PATCH /model/settings {"weights":{"expiry_proximity":9}}` | `200`, generation 2, revenue -> 7.72 |
| Settings reset | `POST /model/settings/reset` | `200`, revenue back to 5.80 |
| CSV export | `GET /export/customers.csv` | `200`, 10 rows, `X-Export-*` headers |
| Playbooks list | `GET /customers/10/recommendations` | `200` |
| Playbook status write | `PATCH /customers/10/recommendations/overdue_renewal {"status":"in_progress"}` | `200`, persists |
| Playbook unknown code | `PATCH .../recommendations/nope` | **404** |
| Playbook invalid status | `PATCH ... {"status":"bogus"}` | **422** |
| Scenario compare | `POST /scenarios/compare` | `200`, baseline vs scenario |
| Quality / priority | `GET /quality`, `GET /priority` | `200` |
| Source snapshot | `GET /source/snapshot` | `200` |

## Browser walkthrough (Chrome via Playwright, local)

Screens visited and verified against the real API on the 10-customer dataset:
login -> dashboard -> customers (sort) -> customer detail -> settings -> what-if.

- Dashboard rendered the correct dataset (10 customers, 3 high / 3 medium /
  4 not applicable) and the money cards.
- What-if comparison ran live: customer #10 `71.4 -> 81.8` and per-customer
  `revenueAtRisk` deltas appeared, matching the API.
- Settings page loaded real settings; the save button reports
  `Настройки сохранены, аналитика пересчитана.` and re-fetches the summary.
- No page-level horizontal overflow observed at desktop width.

## What was NOT verified

| Item | Reason |
| --- | --- |
| `docker compose up --build` in this session | the sandbox already had a Docker stack from a prior session; the Compose file was validated by parsing (`docker-compose.yml` -> 3 services, valid YAML) but a full cold build was not re-run here |
| PostgreSQL as the live store | the walkthrough used SQLite; `psycopg` is installed but no PG connection was made |
| Production VM internals | **no SSH access** - systemd, host nginx, file ownership, backups, the real JWT secret |
| Frontend automated tests | no test runner is configured in `frontend/package.json` |
| Load / soak testing | outside this iteration's scope (measured earlier; see `AGENTS.md`) |

## Reproduce

```bash
# Backend
cd backend && python -m pytest tests/ -q

# Root suite
python -m pytest tests/ -q

# Frontend
cd frontend && npx tsc -b && npm run build
```
