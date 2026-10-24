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
tests/             pytest suite (48 tests)
docs/              REQUIREMENTS_TRACEABILITY.md, ARCHITECTURE.md, DATA_DICTIONARY.md,
                   ANALYTICS_METHODOLOGY.md, REVENUE_METHODOLOGY.md, IMPORT_AND_DATA_AUDIT.md,
                   API_PART_A_LEGACY.md, DEVELOPMENT.md, TESTING.md, DEPLOYMENT.md, SECURITY.md,
                   SCHEMA_MAPPING.md   (docs/API.md documents the canonical part-B API)
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

**Leaked `AEZA_*` shell variables break the test suite.** The test fixtures call
`Settings(...)` with explicit values, but `create_app` reads
`os.getenv("AEZA_ANALYTICS_FACTORY")` and the demo routes read other env vars, so
exporting `AEZA_SEED_DEMO_DATA=1` / `AEZA_DATABASE_URL=...` in the shell makes
`/ready` return 200 and settings tests fail with "unknown factor keys". If tests
fail in a way that makes no sense, run `env | grep ^AEZA_` and unset them first.

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

## Push access blocker and data-set provenance (this checkout)
## Push access blocker (2026-10-24)
`git push` to `Pixelminds-hub/aeza-analizer` fails with
`403 Permission ... denied to Pixelminds-hub`, for `main` **and** for brand-new
branches. The GitHub MCP write path fails the same way
(`Resource not accessible by personal access token`).

Diagnosis: both available credentials (`GITHUB_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`)
belong to the account `Pixelminds-hub` and are GitHub App integration tokens
(`ghu_…`) with **empty** `x-oauth-scopes`. `GET /repos/...` reports
`permissions.push: true`, but the REST branch-protection endpoint answers
`Resource not accessible by integration`, i.e. the token has no `Contents: write`.

Consequence: this environment can read and clone, but cannot write to the remote.
Local `main` is ahead of `origin/main` (14ffdc5) by 13 commits, all verified.
To publish, a token with `Contents: write` (or a push from a machine that has one)
is required. A transferable bundle can be produced with:

    git bundle create /tmp/aeza-sync.bundle origin/main..HEAD

and applied elsewhere with `git fetch /tmp/aeza-sync.bundle main:main`.

## Shipped data set matches README and decks — fixed 2026-10-24
`db/analytics_seed.sql` now carries the **official organiser set: 10 accounts /
30 services / 100 transactions** and one published generation, matching
`dataset/data.json`, `README.md` and the defence decks. Previously it held 60
accounts / 115 services / 285 transactions (10 official + 50 synthetic
`demo-customer-*`), so live row counts and scores disagreed with the decks.

The seed is generated, not hand-edited: load a snapshot into a database with
`backend/scripts/load_snapshot.py`, then dump it with
`backend/scripts/export_seed.py`. Regenerate after changing the source data.
History: `docs/PROVENANCE_AUDIT.md` §6.1.

The seed's *model defaults* were fixed to agree with the code (see below), so
the "sum 15.0 vs code default 13.0" divergence no longer applies.

## Seed/code default divergence — fixed 2026-10-24
`db/analytics_seed.sql` previously stored settings that disagreed with
`DEFAULT_WEIGHTS`: `failed_renewals: 2.0` (a deprecated factor that scoring
ignores), `suspended_status: 2.0` and `renewal_failure_rate: 1.5` (code: 1.0 /
2.5), and it omitted `failedRenewalWindowDays` entirely — which deserialised as
`null` ("whole snapshot") instead of the module's approved 90-day window. The
result was that `GET /model/settings` reported `isDefault: false` on a fresh
install and a reset silently changed the baseline.

All four values are now seeded to match the code, and
`test_bundled_seed_defaults_match_code_defaults` (`backend/tests/test_domain.py`)
fails if the seed ever drifts from `DEFAULT_WEIGHTS` / `RiskSettings()` again.
A fresh database now serves `isDefault: true` and a reset is a true no-op.

## Final readiness pass — 2026-10-24 (verified, not assumed)

Ran after a full fresh-stack rebuild. Every claim below was checked by running a
command against the live stack (`project-api-1` / `project-db-1` / `project-web-1`).

### Documentation defects found and fixed
- `docs/DEMO_SCRIPT.md` claimed the `expiry_proximity 3.0 → 0.5` change moves
  high-risk customers **2 → 1**. Measured: **3 → 0**, low 0 → 1, exposure
  **5,80 € → 4,37 €**. Corrected.
- Same file gave the top customer score as **≈ 73.3**; the real score is
  **71.4** (`user-0010@example.test`). Corrected.
- Earlier in the session: `docs/demo.md` login credential was wrong
  (`aeza-demo-password` → 401; `demo123` → 200), and the stale fallback in
  `backend/app/auth/security.py` plus `docs/deck/capture_shots.py` carried the
  same bad password. All fixed.

### What the live stack actually serves (baseline, generation 3)
- 10 customers / 30 services; high 3, medium 3, low 0, not_applicable 4.
- Revenue at risk **5,80 €**, upcoming renewals **17,03 €**, horizon 30 d.
- `GET /model/settings` → `isDefault: true`, weights sum **13.0**.
- `/metrics`: `aeza_customers_total 10`, `aeza_services_total 30`,
  `aeza_services_open_total 18`, `aeza_revenue_at_risk_eur 5.8`,
  `aeza_upcoming_renewals_eur 17.03`.

### Verification commands that passed
- `cd backend && python -m pytest tests/ -q` → **210 passed**.
- root `python -m pytest tests -q` → **69 passed**.
- `cd frontend && npx tsc -b && npm run build` → clean.
- `python backend/scripts/export_openapi.py` → byte-identical to
  `backend/openapi.json` (19 paths / 21 operations).
- 18-case live API suite (auth, 401/404/422, sort validation, negative weight,
  unknown field) → 18/18.
- Import atomicity: `PUT /source/snapshot` with `transactions[0].amount=5000`
  (schema cap 1000) → 422, generation unchanged, counts unchanged. Re-PUT of the
  same dataset → 200 no-op.
- Workflow persistence: `PATCH /priority/actions` → 200, status `done`,
  note trimmed; re-read confirms persistence; risk score and exposure unchanged.
  Unknown customer / unknown code → 404.

### Browser (Playwright) walkthrough
Dashboard, Customers (numeric sort by `totalReplenished`: 4342,96 → 4206,69 →
2936,08 → 2905,01), Customer #10, Settings, Scenarios, Action Center — all render
live data. Two rendering notes for anyone re-checking by automation:
- The markdown content extractor can serve a stale SPA render right after a
  click; re-read, or navigate straight to the URL, to see the settled table.
- It also surfaces collapsed content that `innerText` omits — the "Экосистема
  Aéza / Виртуальные серверы / …" block is the collapsed logo dropdown in
  `frontend/src/components/AezaLogoDropdown.tsx`, not a layout change.

Mobile invariant re-confirmed at 390×844: `scrollWidth == clientWidth` on all
six routes (`/`, `/action-center`, `/customers`, `/what-if`, `/settings`,
`/customers/10`); the customers table scrolls inside `.table-wrap`
(`overflow-x: auto`, 1208 px of content in a 364 px container).

### Test-residue hygiene
The API verification suite writes a row into `analyzer_action_status`. It was
deleted afterwards; the table is empty on a fresh seed (the seed inserts no
workflow rows). If you run the suite, clean up with:

    sudo docker exec project-db-1 psql -U aeza -d aeza \
      -c "DELETE FROM analyzer_action_status;"

### AI Analyst plan
`docs/AI_ANALYST_PLAN.md` records the verified integration points for a future
local AI Analyst. **Nothing there is implemented**, no model is installed, and no
infrastructure changed — per the task constraint. It reuses the existing
`AEZA_ANALYTICS_FACTORY`-style provider pattern and the existing
`NotReadyError → 503` handler rather than adding a new error path.
# Production deployment (verified against the live stand)

Public stand: `https://aeza-sentinel.pixel-minds.ru/` → `84.201.150.227`
(also the A record for `pixel-minds.ru`). nginx/1.24.0 on Ubuntu terminates TLS
with a Let's Encrypt cert whose SAN covers both names (expires 2027-01-22) and
proxies to the Compose stack. `http://` answers 301 to `https://`.

**The deployed API equals `origin/main`, not the feature branches.** Its
OpenAPI has exactly 18 paths; the Retention Playbooks routes
(`GET/PATCH /api/v1/customers/{id}/recommendations[/{code}]`) exist only on
`feat/priority-whatif-integration` and later, so they return 404 on the stand.
Do not describe the stand as having playbooks until it is redeployed.

`/metrics`, `/api/v1/source/snapshot`, `/api/v1/customers`, `/api/v1/model/settings`
and `/api/v1/analytics/summary` all return 401 without a token — auth is enforced
on the stand. `/health`, `/api/v1/docs` and `/api/v1/openapi.json` are public.
CORS is currently `Access-Control-Allow-Origin: *`.

The agent environment has **no SSH access** to the production VM (no `~/.ssh`,
no keys, no host credentials) — only outbound HTTPS. Any claim about systemd,
nginx internals, file ownership or backups must therefore be marked unverified
and handed to the owner; see `docs/audits/production-readiness-audit.md` §7 for
the exact commands.

## Export must stay streaming
`backend/app/api/routes_export.py` streams one page at a time. Buffering the
whole selection cost ~3.55 GiB resident and ~40 s for 50 000 customers; streaming
caps it at one page (measured +51.5 MiB). If you touch it, keep two invariants:
`X-Export-Rows` reports the **filtered** total (not the base-wide count), and
every page is pinned to the first page's generation so a mid-export
recalculation cannot splice two snapshots.

## Load harness
`backend/scripts/generate_load_profile.py` writes synthetic snapshots with the
organiser schema (`--profile baseline|small|medium|stress`; stress is 50k/200k
≈ 300k tx). `backend/scripts/loadtest.py` drives real routes and reports
p50/p95/p99, RPS and error rate (`--scenario read|mixed|write|whatif|export`).
Both are stdlib-only on purpose so they never enter a production image.

Measured on 4 vCPU / 15.6 GiB: read throughput plateaus at ~115–120 rps with one
`uvicorn` worker, p50 23 ms at c=4 rising to 258 ms at c=32. The 50k `customers`
table is 298 MB; the dominant cost is deserialising 50 000 ~23 KB JSON payloads,
not N+1 or missing indexes.

## Environment caveat
Running the Docker stack plus load tests in the agent sandbox has repeatedly
triggered environment restarts. Keep sweeps short and bounded; capture each
result as you go rather than relying on a long single run.

## AI Analyst: docs must be in the image
`backend/Dockerfile` copies `docs/` and prebuilds the RAG index
(`python -m backend.app.ai.rag`). Without that step the retriever indexes 0
chunks, `/api/v1/ai/status` still reports `ready`, and every answer loses its
grounding silently. If you move `docs/` or change `AEZA_AI_DOCS_PATH`, update the
Dockerfile in the same change.

The Analyst reads `AEZA_AI_*`; the aggregate assistant (`/api/v1/insights/ai`)
reads the older `AEZA_LLM_*`/`AEZA_OLLAMA_*` pair. `docker-compose.yml` passes
both through, so enabling one does not enable the other.

Verified locally against a real model: Ollama `qwen2.5:7b` on the host, API in
Compose, `AEZA_AI_BASE_URL=http://172.18.0.1:11434`. `/api/v1/ai/status` →
`ready`, 691 chunks; `POST /api/v1/ai/customers/{id}/explain` returned a grounded
answer. CPU inference is slow (~20 s short prompt, up to ~3 min with full RAG
context), so keep `AEZA_AI_MAX_CONCURRENCY=1` and expect the UI to wait.
