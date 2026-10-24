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
tests/             pytest suite (69 tests)
docs/              PROJECT_GUIDE.md, AI_ANALYST.md, AI_ASSISTANT.md, AUTH_MODULE.md,
                   DATA_ARCHITECTURE.md, DEPLOYMENT_PART_B.md,
                   PROVENANCE_AUDIT.md, API_PART_A_LEGACY.md, audits/, deck/
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

**Verified 2026-10-24:** the credentials injected into the agent environment
(`GITHUB_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`) are **read-only** on this repo
— every write path returns 403, including `create_branch` and the Contents API.
A **classic** PAT with the `repo` scope is required. With one, the push works:

```bash
git push https://<user>:<CLASSIC_PAT>@github.com/Pixelminds-hub/aeza-analizer.git HEAD:main
```

Two things bite when pushing to `main`:

- **`main` moves under you.** Other contributors push to it directly, so a push
  is often rejected as non-fast-forward. Fetch, merge (never force-push — there
  are 40+ commits from other authors), re-run the tests, then push.
- **Do not `git push --force`.** `main` is shared; a force-push destroys other
  people's work.

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

**A "recalculate" tick must not publish a generation.** `Core.update(force=False)`
returns `previous` when nothing changed. `force=True` exists only for the
engine-version upgrade path in `main.initialize`. Do not reintroduce an
unconditional `recalculate=True` branch: it made `generation` a tick counter and
grew `analyzer_analyses`/`analyzer_customers` by one row per customer per minute.

---

# Operations: backup and restore

`scripts/backup.sh` and `scripts/restore.sh` are the supported backup path.
`backup.sh` uses `pg_dump` for analytics and the SQLite online-backup API for
`auth.sqlite3` (a plain `cp` can tear under a concurrent write). `restore.sh`
does nothing without `--yes`, and removes the `-wal`/`-shm` sidecars before
replacing the auth file — a stale `-wal` shadows the restored database. Backups
land in `backups/`, which is gitignored: they hold real account data.

# Implementations living in this repository

The repository carries **three** bodies of work for the same case. The
analytics implementations remain independent; the Compose API uses the shared
`backend/auth/` module for account storage and token verification.

| Area | What it is | Storage | Entrypoint |
| --- | --- | --- | --- |
| `aeza_analyzer/` | Python package, CLI, vanilla-JS SPA (documented above) | SQLite (`data/`) | `python -m aeza_analyzer.cli serve` |
| `backend/app/` + `frontend/` | FastAPI app + React/TypeScript SPA; delegates authentication to `backend/auth/` | Postgres analytics + separate SQLite accounts | `docker compose up` |
| `backend/auth/`, `backend/main.py` | Shared authentication module (JWT + RSA, own `db/schema.sql`) and standalone OIDC entrypoint | SQLite (`db/auth.sqlite3`) | `backend/main.py` or Compose API |

Note the path collision: `backend/` holds `backend/app/` and the shared
`backend/auth/` module with its standalone `backend/main.py` entrypoint.
`backend/__init__.py` is shared. Check which one you are editing before
changing shared names.

`db/auth.sqlite3` is a runtime store and is ignored by Git. Compose persists it
and `db/private_key.pem` in the `aeza_auth` volume; user records are not seeded.

## Layout

| Path | Purpose |
| --- | --- |
| `dataset/` | Case dataset as shipped (`data.json`, schema/seed SQL, `generate.py`, `README.md`). Read-only source material. |
| `backend/app/domain/` | Business logic: money, scoring, revenue, analytics, importer, settings. No HTTP here. |
| `backend/app/api/` | FastAPI routers, request/response schemas, serializers. |
| `backend/auth/` | Password verification, user repository, RS256 JWTs and OIDC. |
| `backend/data/snapshot.json` | Seed snapshot served on first boot; loaded from `AEZA_SNAPSHOT_PATH`. |
| `backend/migrations/` | Postgres DDL/seed used by the Compose stack. |
| `frontend/src/` | React + TypeScript + Vite SPA. |
| `docs/` | `PROJECT_GUIDE.md` is the current product guide; specialized AI/auth docs and historical materials are separate. |

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

- Create the first auth user explicitly with `docker compose exec api python -m backend.users create <login>`.
- Set `AUTH_ISSUER` to the public HTTPS origin and `AUTH_COOKIE_SECURE=true` in production; the RSA key is persisted in the auth volume.
- Compose uses a throwaway Postgres password (`aeza`) for local demos. Replace it before exposing the stack to anyone.
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

## Authentication dependency
The Compose API and standalone auth entrypoint share `backend/auth/` and use
`PyJWT[crypto]` for RS256 tokens. The API does not bootstrap an account or
require a shared JWT secret; users are created in the auth SQLite database.

## Test coverage gaps
No frontend test runner is configured (`frontend/package.json` has no `test`
script and no vitest/jest/playwright dependency). Verify the UI manually before
release; the current user-facing overview is in `docs/PROJECT_GUIDE.md`.

## Push access to this checkout (updated 2026-10-24)

**Publishing now works, but only with a classic PAT supplied per command.**
The credentials injected into the agent environment (`GITHUB_TOKEN`,
`GITHUB_PERSONAL_ACCESS_TOKEN`) are GitHub App tokens (`ghu_…`) with empty
`x-oauth-scopes`; `GET /repos/...` still reports `permissions.push: true`, yet
every write path returns `403 Permission … denied` (push, `create_branch`, the
Contents API). A **classic** PAT with the `repo` scope pushes successfully:

```bash
git push https://<user>:<CLASSIC_PAT>@github.com/Pixelminds-hub/aeza-analizer.git HEAD:main
```

Three things bite, all hit in practice:

- **`~/.gitconfig` injects a competing helper.** It sets
  `credential.https://github.com.helper = !/usr/bin/gh auth git-credential`,
  which is URL-scoped and therefore *overrides* a plain `credential.helper`.
  A `-c credential.helper=store` flag alone is silently ignored and the 403
  comes back. Reset the list first, then set the scoped helper:
  `git -c credential.helper= -c credential.https://github.com.helper='store --file=<f>' push …`
- **`main` moves under you.** Other contributors push directly, so a push is
  often rejected as non-fast-forward. Fetch, merge (never force-push — there are
  40+ commits from other authors), re-run the tests, then push.
- **Never `git push --force`** and never leave a token in `.git/config` or in a
  committed file.

## Data-set provenance and seed alignment — fixed 2026-10-24

`db/analytics_seed.sql` carries the **official organiser set: 10 accounts /
30 services / 100 transactions** with one published generation, matching
`dataset/data.json`, `README.md` and the defence decks. It previously held 60
accounts / 115 services / 285 transactions (10 official + 50 synthetic
`demo-customer-*`), so live row counts and scores disagreed with the decks.

The seed is generated, not hand-edited: load a snapshot into a database with
`backend/scripts/load_snapshot.py`, then dump it with
`backend/scripts/export_seed.py`. Regenerate after changing the source data.
History: `docs/PROVENANCE_AUDIT.md` §6.1.

The seed's *model defaults* were also aligned with the code:
`failed_renewals: 2.0` (a deprecated factor scoring ignores),
`suspended_status: 2.0` and `renewal_failure_rate: 1.5` (code: 1.0 / 2.5) were
corrected, and `failedRenewalWindowDays` (previously omitted, deserialising as
`null` = "whole snapshot" instead of the approved 90-day window) is now seeded.
`test_bundled_seed_defaults_match_code_defaults` fails if the seed drifts from
`DEFAULT_WEIGHTS` / `RiskSettings()`. A fresh database serves `isDefault: true`
and a reset is a true no-op.

## Final readiness pass — 2026-10-24 (verified, not assumed)

Ran against the live stack (`project-api-1` / `project-db-1` / `project-web-1`).

### Documentation defects found and fixed
- `docs/DEMO_SCRIPT.md` claimed the `expiry_proximity 3.0 → 0.5` change moves
  high-risk customers **2 → 1**. Measured: **3 → 0**, low 0 → 1, exposure
  **5,80 € → 4,37 €**. Corrected.
- Same file gave the top customer score as **≈ 73.3**; the real score is
  **71.4** (`user-0010@example.test`). Corrected.
- `docs/demo.md` login credential was wrong (`aeza-demo-password` → 401;
  `demo123` → 200), and the stale fallback in `backend/app/auth/security.py`
  plus `docs/deck/capture_shots.py` carried the same bad password. Fixed.

### What the live stack actually serves (baseline, generation 3)
- 10 customers / 30 services; high 3, medium 3, low 0, not_applicable 4.
- Revenue at risk **5,80 €**, upcoming renewals **17,03 €**, horizon 30 d.
- `GET /model/settings` → `isDefault: true`, weights sum **13.0**.
- `/metrics`: `aeza_customers_total 10`, `aeza_services_total 30`,
  `aeza_services_open_total 18`, `aeza_revenue_at_risk_eur 5.8`,
  `aeza_upcoming_renewals_eur 17.03`.

Weight changes drive real recalculation: `expiry_proximity 3.0 → 9.0` bumps
`modelVersion`, moves exposure **5,80 € → 7,72 €**, and persists across a fresh
read. (A probe that reads `weights` at the top level of the `PATCH` response
returns `None` — the value is nested under `settings.weights`; that is a probe
bug, not a store bug.)

### Verification commands that passed
- `python -m pytest backend/tests -q` → **325 passed**.
- root `python -m pytest tests -q` → **69 passed**.
- `cd frontend && npx tsc -b && npm run build` → clean.
- 28 OpenAPI paths in `backend/openapi.json`, matching the served schema.
- Live API suite (auth, 401/404/422, sort validation, negative weight, unknown
  field) → all pass.
- Import atomicity: `PUT /source/snapshot` with `transactions[0].amount=5000`
  (schema cap 1000) → 422, generation and counts unchanged. Re-PUT of the same
  dataset → 200 no-op.
- Workflow persistence: `PATCH /priority/actions` → 200, status `done`, note
  trimmed; re-read confirms persistence; unknown customer / code → 404.

### Browser (Playwright) walkthrough
Dashboard, Customers (numeric sort by `totalReplenished`), Customer #10,
Settings, Scenarios, AI Analyst — all render live data. Two rendering notes for
anyone re-checking by automation:
- The markdown content extractor can serve a stale SPA render right after a
  click; re-read, or navigate straight to the URL, to see the settled table.
- It also surfaces collapsed content that `innerText` omits — the "Экосистема
  Aéza / Виртуальные серверы / …" block is the collapsed logo dropdown in
  `frontend/src/components/AezaLogoDropdown.tsx`, not a layout change.

Mobile invariant re-confirmed at 390×844: `scrollWidth == clientWidth` on all
routes; the customers table scrolls inside `.table-wrap`.

### Test-residue hygiene
The API verification suite writes a row into `analyzer_action_status`. Delete it
afterwards (the seed inserts no workflow rows):

    sudo docker exec project-db-1 psql -U aeza -d aeza \
      -c "DELETE FROM analyzer_action_status;"

## Compose / clean-checkout fixes (verified by running the stack)

These were real defects that only appear on a clean checkout or a shared host.

- **Stale, wrong seed.** `db/analytics_seed.sql` held a **different** dataset
  (60 accounts / 115 services / 285 transactions) than the official snapshot.
  Compose used to pre-load it via an initdb bind-mount. It is no longer mounted;
  the API now seeds `dataset/data.json` (10/30/100) through its own validated
  importer (`AEZA_SEED_DEMO_DATA=1`, `AEZA_SNAPSHOT_PATH=/app/dataset/data.json`).
- **Auth DB as a bind mount was wrong.** `db/auth.sqlite3` is gitignored, so a
  file bind-mount would create a *directory* on a clean checkout, and a `./db`
  bind-mount would impose the host uid on `/app/db` (the container runs as uid
  10001). Both are replaced by a **named volume** `auth_data:/app/db`, seeded
  from the image so permissions are correct. Postgres likewise uses `pg_data`.
- **No default secret for the database.** Compose fails closed on
  `POSTGRES_PASSWORD` alone (${VAR:?…}); `docker compose config` exits 1 without
  it. The old `AEZA_JWT_SECRET`/`AEZA_ADMIN_*` requirements were removed with the
  auth rewrite: nothing reads them any more, and requiring them blocked a fresh
  checkout from starting. CORS defaults to `http://localhost:8080`, never `*`.
- **Login field is `access_token`** (snake_case), not `accessToken`.
- **Invalid `sortBy` returns an empty page, not 422.** `GET /customers?sortBy=risk`
  (wrong key) silently yields `items: []`. Use `riskScore`. Worth tightening.

## CI

`.github/workflows/ci.yml` runs backend tests, root tests, frontend
typecheck+build, and Compose config validation (including the fail-closed check).
There was no CI before; this is new.

## Local AI Analyst — verified on live inference

The AI Analyst is not a mock. It was run end-to-end against a real local model.

- Ollama 0.40.10, `qwen2.5:3b-instruct` (1.9 GB, Q4), CPU only, 4 vCPU.
- API runs in Compose; the model runs on the host. `docker-compose.yml` sets
  `extra_hosts: host.docker.internal:host-gateway` on the `api` service, and
  `AEZA_AI_BASE_URL` defaults to `http://host.docker.internal:11434`.
- **Ollama must not bind loopback-only** if the API is containerised: bind the
  docker bridge (`OLLAMA_HOST=172.17.0.1:11434 ollama serve`), not 0.0.0.0.
  Loopback bind is the #1 cause of a misleading `unavailable` status.
- The RAG index is built **at image build time** (`backend/Dockerfile` copies
  `docs/` and runs `python -m backend.app.ai.rag`). It is gitignored
  (`backend/data/rag_index.json`), so it must be produced in the image, not
  committed. **If `docs/` is not copied the retriever indexes 0 chunks while
  `/ai/status` still reports `ready`, and every answer silently loses grounding.**
- Verified: money question answers "5.80 EUR" grounded with citations;
  `customerId=5` yields `riskScore=71.4` (exactly the engine value); methodology
  questions cite `docs/model.md`; prompt injection is refused; `/ai/*` returns
  401 without a token; `AEZA_AI_ENABLED=0` returns 503 while analytics keeps
  working.
- Latency on this CPU: **37–91 s** per answer with the 3b model. A **cold**
  explain call on `qwen2.5:7b` measured **196.6 s / 303.7 s**, warm 171.8 s —
  which is why `AEZA_AI_TIMEOUT_SECONDS` defaults to **420**, not 180: a shorter
  budget rejects a healthy model with 503 on the first request after a restart.
  `AEZA_AI_MAX_CONCURRENCY=1`, so requests queue. Fine for a demo, not for
  concurrent analysts — that needs a separate inference host.
# Production deployment (verified against the live stand)

Public stand: `https://aeza-sentinel.pixel-minds.ru/` → `84.201.150.227`
(also the A record for `pixel-minds.ru`). nginx/1.24.0 on Ubuntu terminates TLS
with a Let's Encrypt cert whose SAN covers both names (expires 2027-01-22) and
proxies to the Compose stack. `http://` answers 301 to `https://`.

The deployed API was last verified with 18 OpenAPI paths. The current local
OpenAPI includes Retention Playbooks routes
(`GET/PATCH /api/v1/customers/{id}/recommendations[/{code}]`); their presence
on the public stand must be checked against that stand's own OpenAPI before
being documented as deployed.

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
