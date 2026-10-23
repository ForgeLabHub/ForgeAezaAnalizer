# AGENTS.md

Working notes for agents and contributors touching this repository.

## What this is

`Aéza · Churn Risk Analyzer` — case #2 for UMIRHack 2026. It reads a customer
snapshot (accounts, services, transactions), scores churn risk with an
explainable weighted model, and estimates the revenue exposed inside a
forecast horizon. UI and user-facing text are in Russian.

## Layout

| Path | Purpose |
| --- | --- |
| `dataset/` | Case dataset exactly as shipped (`data.json`, schema/seed SQL, `generate.py`, `README.md`). Treat as read-only source material. |
| `backend/app/domain/` | Business logic: money, scoring, revenue, analytics, importer, settings. No HTTP here. |
| `backend/app/api/` | FastAPI routers, request/response schemas, serializers. |
| `backend/app/auth/` | JWT issuing/verification and PBKDF2 password hashing. |
| `backend/data/snapshot.json` | Seed snapshot served on first boot; loaded from `AEZA_SNAPSHOT_PATH`. |
| `backend/migrations/` | Postgres DDL/seed used by the Compose stack. |
| `frontend/src/` | React + TypeScript + Vite SPA. |
| `docs/` | Data schema, model, import contract, demo script, readiness report. |

## Commands

```bash
# Backend tests (from backend/)
python -m pytest tests/ -q

# Frontend typecheck + build (from frontend/)
npx tsc -b && npm run build

# Full stack (Postgres + API + nginx) from the repo root
sudo docker compose up -d --build
# API on :8000, SPA on :8080
```

## Invariants worth preserving

- **Money is integer eurocents** in the backend. Convert only at the edge
  (`backend/app/domain/money.py`). 100 cents = €1. Never mix balance, bonus
  balance, historical top-ups, service price, and revenue-at-risk.
- **The risk score is not a probability.** The snapshot has no historical churn
  outcomes, so the model is a transparent weighted rule-based score. Do not
  describe it as a calibrated probability or claim accuracy in the UI or docs.
- **Keep three states apart:** current state, already-concluded events, and
  forward-looking risk. `deleted`/`blocked` services are concluded — they must
  not be forecast as future churn, and they are not `not_applicable` silently.
- **Price never feeds the risk score.** Cost is exposure, not likelihood.
- **Customer risk is the max over forecastable services**, not an average.
- **Revenue at risk counts each renewal once**, only for open services with a
  positive price renewing inside the horizon.
- **Reference time is pinned** to `2026-10-19T15:00:00Z` (`AEZA_AS_OF`) so scores
  are reproducible. Change it deliberately, not incidentally.
- **Import is all-or-nothing.** Validate the whole snapshot before writing;
  a rejected import must leave the previous dataset untouched.

## Gotchas

- `AEZA_JWT_SECRET` must be set (with `AEZA_ALLOW_DEV_SECRET=0`) outside local
  development; the app refuses to invent a secret in shared environments.
- Compose uses a throwaway Postgres password (`aeza`) for local demos. Replace
  it and the JWT secret before exposing the stack to anyone.
- After changing factor weights, results change but `/metrics` reflects the
  latest computed values — recompute before reading gauges.
- The frontend table must stay inside `.table-wrap`; page-level horizontal
  overflow at narrow widths is a regression.
