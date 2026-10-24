# AGENTS.md — Aéza Analyzer

Repository-specific notes for future agent sessions.

## What this project is

A churn-risk / revenue-at-risk analytics app for the Aéza hackathon case,
built on the organiser dataset shipped as `датасет.zip` in the repo root.

**Important history:** the repository originally contained *only* a 15-byte
README and the dataset ZIP — there was no application code. The whole app was
written during the integration task, so there is no pre-existing architecture to
preserve. Do not assume an older frontend/backend exists.

## Layout

```
aeza_analyzer/
  config.py        env-driven paths (lazy: reads env on each access)
  money.py         eurocents -> euros (100:1), None stays None
  models.py        SQLAlchemy models mirroring source columns 1:1
  db.py            engine/session; SQLite FK pragma; reset_state() for tests
  audit.py         reproducible data profile
  cli.py           `import` / `audit` / `serve`
  importer/
    archive.py     safe ZIP extraction (traversal, dupes, bombs, symlinks)
    validation.py  per-record validation against the source contract
    loader.py      atomic + idempotent load, import_runs audit trail
  analytics/
    risk.py        weighted explainable scoring (NOT a trained ML model)
    service.py     customer risk, revenue at risk, dashboard
  api/app.py       FastAPI endpoints
  static/          vanilla-JS SPA (index.html, app.js, styles.css)
tests/             pytest suite (52 tests)
docs/              REQUIREMENTS_TRACEABILITY.md, ARCHITECTURE.md, DATA_DICTIONARY.md,
                   ANALYTICS_METHODOLOGY.md, REVENUE_METHODOLOGY.md, IMPORT_AND_DATA_AUDIT.md,
                   API.md, DEVELOPMENT.md, TESTING.md, DEPLOYMENT.md, SECURITY.md, SCHEMA_MAPPING.md
```

## Commands

```bash
pip install -r requirements.txt
python -m aeza_analyzer.cli import     # loads датасет.zip -> data/aeza.sqlite
python -m aeza_analyzer.cli audit      # JSON data profile
python -m aeza_analyzer.cli serve --port 8000
python -m pytest tests/ -q
```

`data/` is gitignored. The original `датасет.zip` is the source of truth and is
never modified.

## Non-obvious invariants (easy to break)

- **Money is integer eurocents everywhere internally.** Euros appear only as
  `*_eur` string fields added at the API boundary. Never divide twice.
- **`transactions.amount` is NOT money.** The organiser README states it is
  generated independently of `price`; do not convert it or use it in revenue.
- **Unknown ≠ zero.** A feature with missing input is `None`, dropped from both
  the numerator and denominator; `confidence` records the coverage. Never let a
  missing signal lower risk.
- **`deleted` services are already-churned history**, excluded from forward
  scoring. Accounts with only deleted services get level `churned`, not `low`.
- **`reference_at` is derived from the data** (max `createdAt`/`performedAt`),
  not from wall-clock time, so results are reproducible.
- **Import is atomic + idempotent.** It replaces fixture tables inside one
  transaction; any rejected row aborts the whole import by default.
- SQLite has no native tz support — `models.UTCDateTime` re-attaches UTC on read.
  Comparisons of stored vs computed datetimes depend on this.
- `level_for()` bands are low 0–34, medium 35–64, high 65–100; fractional
  scores in the gaps (e.g. 34.9) stay in the lower band.

## Pushing to GitHub

`git push origin main` works when a token with `contents: write` on
`Pixelminds-hub/aeza-analizer` is supplied in the remote URL. The OpenHands app
installation does **not** cover this repo (it is installed on `Pavel1778` and
`Pixel-Minds`, which are different accounts from the owning user
`Pixelminds-hub`), so pushes fail with 403 unless the URL carries an explicit
token. The token itself is never stored in `.git/config` — pass it per command:

```bash
git push https://<TOKEN>@github.com/Pixelminds-hub/aeza-analizer.git main
```

Never commit a token, and never leave one in the remote URL.

## Gotchas that already bit us

`from .config import settings` binds the `settings` object; `Settings` reads
env vars lazily (properties) precisely so tests can repoint `AEZA_DATA_DIR`
without reloading modules. Keep it lazy.

Also avoid naming a loop/local variable `service` in API handlers — it shadowed
the analytics service and caused a 500.

---

# Implementations living in this repository

The repository carries **three** independently written bodies of work for the
same case. None of them imports from the others, and each has its own storage
layer, scoring code and entrypoint. Do not delete one to "clean up" another.

| Area | What it is | Storage | Entrypoint |
| --- | --- | --- | --- |
| `aeza_analyzer/` | Python package, CLI, vanilla-JS SPA (documented above) | SQLite (`data/`) | `python -m aeza_analyzer.cli serve` |
| `backend/app/` + `frontend/` | FastAPI app + React/TypeScript SPA (documented below) | Postgres via Compose, SQLite for tests | `docker compose up` |
| `backend/auth/`, `backend/main.py` | Standalone auth module (JWT + RSA, own `db/schema.sql`) | SQLite (`db/auth.sqlite3`) | `backend/main.py` |

Note the path collision: `backend/` holds two unrelated trees — `backend/app/`
(below) and `backend/auth/` + `backend/main.py` + `backend/config.py`
(the standalone auth module). `backend/__init__.py` is shared. Check which one
you are editing before changing shared names.

`db/auth.sqlite3` is committed but holds no user rows (verified: the `users`
table is empty). It is the auth module's runtime store, not fixture data.

## Layout

| Path | Purpose |
| --- | --- |
| `dataset/` | Case dataset as shipped (`data.json`, schema/seed SQL, `generate.py`, `README.md`). Read-only source material. |
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
  not be forecast as future churn.
- **Price never feeds the risk score.** Cost is exposure, not likelihood.
- **Customer risk is the max over forecastable services**, not an average.
- **Revenue at risk counts each renewal once**, only for open services with a
  positive price renewing inside the horizon.
- **Reference time is pinned** to `2026-10-19T15:00:00Z` (`AEZA_AS_OF`) so scores
  are reproducible. Change it deliberately, not incidentally.
- **Import is all-or-nothing.** Validate the whole snapshot before writing; a
  rejected import must leave the previous dataset untouched.

## Gotchas

- `AEZA_JWT_SECRET` must be set (with `AEZA_ALLOW_DEV_SECRET=0`) outside local
  development; the app refuses to invent a secret in shared environments.
- Compose uses a throwaway Postgres password (`aeza`) for local demos. Replace
  it and the JWT secret before exposing the stack to anyone.
- The frontend table must stay inside `.table-wrap`; page-level horizontal
  overflow at narrow widths is a regression (the header wraps at ≤720px).

# Architecture review findings (verified, not assumed)

Facts established by reading the code and querying the committed dataset. Each
line below was checked by running a command, not inferred from naming.

## Data provenance
- `dataset/data.json` and `датасет.zip!датасет/data.json` are byte-identical
  (sha256 `6e0e224671a4cd22…`). The zip additionally ships `test_generate.py`,
  which is NOT extracted into `dataset/` — the only zip member missing from the
  working tree.
- The dataset is synthetic, generated by `dataset/generate.py`. `README.md`
  previously called it "реальных данных организатора" while its own §8 said
  "синтетические"; corrected.

## Service field names (verify before use)
`services[]` has `ownerId`, not `accountId`. Fields: `id, name, ownerId,
paymentTerm, autoProlong, createdAt, expiresAt, status, price`. Transactions
carry `serviceId` and both `createdAt` and `performedAt`.

## Latent divergence: balance vs withdrawBalance
Part A's `insufficient_balance` factor uses `withdrawBalance`; part B's uses
`balance`. Measured impact on the shipped dataset: **zero**. Across every open
service with `price > 0`, and at horizons 30/60/90/180/365 days, the two fields
never disagree on sufficiency (0 disagreeing pairs). The divergence is real but
cannot manifest here, because `min(withdrawBalance) = 425` exceeds every price
that is actually due, and the largest price (960) belongs to an account whose
both fields cover it. A dataset with a large `price` against a drained
`withdrawBalance` would expose it.

## Per-request recomputation (scaling limit)
`AnalyticsService.analyze_all()` re-scores every account on each call, and both
`GET /customers` and `GET /customers/{id}` call it. There is no cache anywhere
in `backend/app/`. Sorting and filtering happen in Python after the full load,
not in SQL, so `sortBy`/`search` cannot use an index. N+1 is avoided via
`selectinload(AccountRow.services).selectinload(ServiceRow.transactions)`, so
this is CPU-bound, not query-bound. Fine for 10 accounts; it is the first thing
to change for a real customer base.

## Two JWT libraries in one repository
`backend/app/auth/security.py` uses `python-jose`; `backend/auth/tokens.py` and
`backend/auth/service.py` use `pyjwt`. Both are declared now (part B via
`backend/requirements.txt`, part C via the root `requirements.txt`). Parts B and
C do not share an auth path: B is HS256 with a shared secret, C is RS256 with a
generated RSA keypair and OIDC-style discovery/JWKS routes.

## Test coverage gaps
No frontend test runner is configured (`frontend/package.json` has no `test`
script and no vitest/jest/playwright dependency). The UI is verified only by the
manual browser walkthrough in `docs/demo.md`.

## Compose / clean-checkout fixes (verified by running the stack)

These were real defects that only appear on a clean checkout or a shared host.

- **Stale, wrong seed.** `db/analytics_seed.sql` held a **different** dataset
  (60 accounts / 115 services / 285 transactions) than the official snapshot.
  Compose used to pre-load it via an initdb bind-mount. It is no longer mounted;
  the API now seeds `dataset/data.json` (10/30/100) through its own validated
  importer (`AEZA_SEED_DEMO_DATA=1`, `AEZA_SNAPSHOT_PATH=/app/dataset/data.json`).
  The image copies `dataset/data.json`. Counts are asserted in the README
  acceptance table and in `/api/v1/source/snapshot`.
- **Auth DB as a bind mount was wrong.** `db/auth.sqlite3` is gitignored, so a
  file bind-mount would create a *directory* on a clean checkout, and a `./db`
  bind-mount would impose the host uid on `/app/db` (the container runs as uid
  10001). Both are replaced by a **named volume** `auth_data:/app/db`, seeded
  from the image so permissions are correct. Postgres likewise uses `pg_data`.
- **No default secrets.** Compose fails closed: `POSTGRES_PASSWORD`,
  `AEZA_JWT_SECRET`, `AEZA_ADMIN_EMAIL`, `AEZA_ADMIN_PASSWORD` use `${VAR:?…}`.
  `docker compose config` exits 1 without them. CORS defaults to
  `http://localhost:8080`, never `*`.
- **Login field is `access_token`** (snake_case), not `accessToken`.
- **Invalid `sortBy` returns an empty page, not 422.** `GET /customers?sortBy=risk`
  (wrong key) silently yields `items: []`. Use `riskScore`. Worth tightening.

## CI

`.github/workflows/ci.yml` runs backend tests, root tests, frontend
typecheck+build, and Compose config validation (including the fail-closed check).
There was no CI before; this is new.

## Local AI Analyst — verified on live inference

The AI Analyst is not a mock. It was run end-to-end against a real local model:

- Ollama 0.40.10, `qwen2.5:3b-instruct` (1.9 GB, Q4), CPU only, 4 vCPU.
- API runs in Compose; the model runs on the host. `docker-compose.yml` sets
  `extra_hosts: host.docker.internal:host-gateway` on the `api` service, and
  `AEZA_AI_BASE_URL` defaults to `http://host.docker.internal:11434`.
- **Ollama must not bind loopback-only** if the API is containerised:
  `OLLAMA_HOST=0.0.0.0:11434 ollama serve`. Loopback bind is the #1 cause of a
  misleading `unavailable` status.
- The RAG index is built **at image build time** (`backend/Dockerfile` copies
  `docs/` and runs `python -m backend.app.ai.rag`). 324 chunks. It is gitignored
  (`backend/data/rag_index.json`), so it must be produced in the image, not
  committed.
- Verified: money question answers "5.80 EUR" grounded with citations;
  `customerId=5` yields `riskScore=71.4` (exactly the engine value); methodology
  questions cite `docs/model.md`; prompt injection is refused; `/ai/*` returns
  401 without a token; `AEZA_AI_ENABLED=0` returns 503 while analytics keeps
  working.
- Latency on this CPU: **37–91 s** per answer (`num_ctx=4096`,
  `max_tokens=1200`). `AEZA_AI_MAX_CONCURRENCY=1`, so requests queue. Fine for a
  demo, not for concurrent analysts — that needs a separate inference host.
