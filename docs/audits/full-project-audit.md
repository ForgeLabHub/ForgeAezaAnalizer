# Full project audit — Aéza Sentinel

Date: 2026-10-24. Branch: `main`. Audited commit: `ce802ba` (fix) on top of
`30cb55e`.

Scope: the whole repository, with priority on the reported production defect
(`UndefinedColumn` on the Telegram link table), then database lifecycle, API,
Telegram, e-mail, AI, frontend, security, Docker and tests.

Every claim below is backed by a command that was run. Where a check could not be
performed it is labelled **NOT RUN** or **BLOCKED** with the reason.

---

## 1. Summary

The reported production defect was reproduced exactly and fixed. It was not a
Telegram-specific bug but a **schema-management gap**: `create_all()` never alters
an existing table, so any release that adds a column starts against a database
whose shape no longer matches the ORM. The fix makes that impossible for the whole
schema, not just the reported table.

| | |
| --- | --- |
| Reproduced | `psycopg.errors.UndefinedColumn: column analyzer_telegram_links.telegram_user_id does not exist` |
| Root cause | `Base.metadata.create_all()` creates missing tables only; it never migrates existing ones |
| Fix | `backend/app/schema.py` — additive column reconciliation + recorded migrations, run on every start |
| Also added | `backend/app/schema_check.py` — read-only drift check for pre-deploy use |
| Tests | 486 backend tests pass, including 10 new schema/migration tests |
| Production | **Not deployed from this session** (see §11) |

---

## 2. Architecture (as found)

| Layer | Component |
| --- | --- |
| API | FastAPI (`backend/app/main.py`), 47 OpenAPI paths |
| Analytics | `backend/app/domain/` (risk engine), `core.py` (`Core`, `Storage`) |
| DB | PostgreSQL 16; SQLAlchemy 2 ORM (`backend/app/db.py`) |
| Auth | `backend/auth/` (RS256 JWT, scrypt, SQLite account store) |
| Telegram | `backend/app/telegram/` + `api/routes_telegram.py` + `api/routes_client.py` |
| E-mail | `backend/app/integrations/email.py` (SMTP.BZ + Yandex Cloud Postbox) |
| AI | `backend/app/ai/` (Ollama + RAG) |
| Frontend | React + TypeScript + Vite (`frontend/`), nginx reverse proxy |
| Deploy | Docker Compose (`docker-compose.yml`), host nginx terminates TLS |

Two Telegram generations exist in history: an earlier one (removed in `2002e74`)
and the current client-facing one. **They collide on the table name
`analyzer_telegram_links` with different columns** — the cause of the outage.

---

## 3. Components checked

- `backend/app/db.py` — all 18 ORM models; `Database.initialize()`.
- `backend/migrations/*.sql` — found to be **dead**: no code, Compose file or
  script references them (they belong to the dataset README's manual `psql` flow).
- `backend/app/api/` — every router; authorization probed route by route.
- `backend/app/telegram/` — service, providers, webhook, OTP, notifications, support.
- `backend/app/integrations/email.py` — both transports.
- `backend/app/ai/` — service, providers, safety, RAG.
- `frontend/` — build, routes, API client, Mini App.
- `docker-compose.yml`, Dockerfiles, nginx config.
- `docs/`, `.env.example`, `backend/requirements.txt`.

---

## 4. Defects

| # | Sev | Defect | Evidence | Status |
| --- | --- | --- | --- | --- |
| D1 | **P0** | `analyzer_telegram_links` kept the legacy shape; the ORM expected `telegram_user_id` etc. Every link read/write failed, including the analyst replying to a support thread | Reproduced locally: legacy table + `analyst_reply()` → `psycopg.errors.UndefinedColumn` | **FIXED** |
| D2 | P1 | `create_all()` cannot alter existing tables, so the whole class of "new release adds a column" bugs was latent | `backend/app/db.py` `initialize()` before the fix | **FIXED** |
| D3 | P2 | No way to detect ORM/database drift before a deploy | — | **FIXED** (drift checker) |
| D4 | P2 | `backend/migrations/*.sql` looks like the migration mechanism but nothing runs it | `grep -rn migrations` → no code reference | **DOCUMENTED** |
| D5 | P2 | Production nginx still sends `X-Frame-Options: DENY` and no HSTS (the repo's `frontend/nginx.conf` was fixed on `main`, the stand was not rebuilt) | `curl -D-` on the stand | **BLOCKED** (needs deploy) |
| D6 | P3 | Local `.venv` was missing `aiosmtpd`, a declared test dependency, so `test_postbox.py` failed to import | `pytest` collection error | **FIXED locally** (env, not code) |

Not found: any route reachable without authentication (all 47 probed), any
`X-Frame-Options`/CSP test that the nginx change broke, any secret in the working
tree or the diff.

---

## 5. Fix detail (D1–D3)

`backend/app/schema.py`, called from `Database.initialize()` after `create_all`:

1. **`reconcile(engine)`** — for every existing model table, add any missing column
   as nullable (with a literal server default where the model has one). Additive
   only: nothing is dropped, truncated or retyped. This fixes D1 *and* every future
   case of the same class, because it compares the models to the live database on
   each start rather than trusting a table's presence.
2. **`apply_migrations(engine)`** — an ordered registry for changes an additive
   pass cannot express, recorded in `schema_migrations` so each runs at most once.
   The single migration backfills:
   - `telegram_user_id` ← `chat_id` (the earlier bot served private chats only,
     where `chat_id` is the user id);
   - `account_id` ← the analytics account whose email matches the legacy
     `user_email`, **only when the match is unambiguous**.

   A row that cannot be mapped is left with a NULL `account_id` and logged — never
   deleted, never assigned to an arbitrary account.

`backend/app/schema_check.py` reports drift read-only (`exit 1` on drift) and never
prints the database URL, which carries the password.

### Why this is safe on production

- No `DROP`, `TRUNCATE`, `DELETE` or type change anywhere in the module.
- A migration that cannot proceed safely raises instead of guessing, and is not
  recorded, so the next start retries rather than leaving a half state.
- Each migration runs in its own transaction.

---

## 6. Migrations added

| Version | What it does |
| --- | --- |
| `2026_10_24_telegram_link_legacy_shape` | Backfills `telegram_user_id` from `chat_id` and `account_id` from `user_email` on a legacy `analyzer_telegram_links` |

Applied automatically by `Database.initialize()` on the next start, on both
PostgreSQL and SQLite. **It has not been applied to production from this session**
(no server access — §11).

---

## 7. Tests run

| Check | Command | Result |
| --- | --- | --- |
| Backend suite | `pytest backend/tests -q` | **486 passed** |
| New schema/migration tests | `pytest backend/tests/test_schema_migrations.py -q` | **10 passed** |
| Postgres reproduction + fix | legacy table, then `initialize()` | columns added, `analyst_reply()` OK, re-run no-op |
| Route authorization | every OpenAPI route probed without a token | **0 reachable** outside the known-public set |
| API smoke (with token) | 15 endpoints incl. `/metrics`, `/email/status`, `/telegram/*` | all 200 |
| Telegram support flow | start → analyst reply → read history | 201/201/200 |
| Docs gate | `python backend/scripts/check_docs.py` | 4/4 ok |
| Frontend | `npx tsc -b && npm run build` | clean |
| Compose | `docker compose config`; fail-closed without `POSTGRES_PASSWORD` | valid; refuses as intended |
| Secret scan | `git diff` grep for token/key patterns | none |

**BLOCKED / NOT RUN:** live Telegram Bot API (`getMe`, `getWebhookInfo`) — no
token available to this session; live AI request — Ollama is on the stand, not
reachable from here; production deploy — no server access.

---

## 8. Confirmed on production (read-only)

| Check | Result |
| --- | --- |
| `/`, `/health`, `/ready`, `/api/v1/openapi.json` | **200** (the earlier 502 is gone) |
| `/api/v1/email/status` without a token | **401** (auth enforced) |
| OpenAPI path count | 47 |
| Security headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` — **no HSTS**, and the DENY still blocks the Mini App iframe |

The stand serves a **build without the schema fix**; `X-Frame-Options: DENY`
confirms the nginx change on `main` is not deployed either.

---

## 9. Residual risks

1. **The fix is published but not deployed** — production keeps failing on the
   legacy table until `api` is rebuilt (§12).
2. **Legacy columns remain** (`chat_id`, `user_email`, `username`). They are
   harmless and preserved deliberately; dropping them is a separate, owner-approved
   change.
3. **Unmapped legacy links** (if any exist on the stand) will have a NULL
   `account_id` and be ignored until re-linked. The migration logs the count.
4. `backend/migrations/*.sql` still looks authoritative but is not wired; a future
   contributor could add a migration there and expect it to run.
5. No HSTS on the stand.
6. Secrets that appeared in earlier chat history remain a rotation candidate
   (names only, no values): `POSTGRES_PASSWORD`, `AEZA_TELEGRAM_BOT_TOKEN`,
   `AEZA_TELEGRAM_WEBHOOK_SECRET`, `SMTP_*` credentials, `AEZA_METRICS_TOKEN`,
   GitHub PATs.

---

## 10. Deploy instructions

```bash
cd ~/aeza-analizer
git fetch origin && git log --oneline -1 origin/main     # expect ce802ba or later

# 1. See the drift BEFORE changing anything (read-only, safe):
docker compose exec -T api python -m backend.app.schema_check
#    exit 0 = no drift; exit 1 = drift listed (the release reconciles columns itself)

# 2. Back up the database first (scripts/backup.sh uses pg_dump):
./scripts/backup.sh

# 3. Rebuild and restart only what changed:
docker compose up -d --build api web
docker compose ps
curl -fsS localhost:8000/health && echo && curl -fsS localhost:8000/ready && echo
```

`initialize()` runs the reconciliation on start; the log will show
`schema.reconcile: added missing column ...` and `schema.migration: applied ...`
once, then nothing on later restarts.

**Never** `docker compose down -v`: that deletes `pg_data` and `auth_data`.

### Rollback

```bash
git log --oneline -5                     # find the previous commit
git checkout <previous-commit>
docker compose up -d --build api web
```

Rollback is safe for the schema: the reconciliation only *adds* columns, so an
older release ignores the extra ones. No migration in this release removes or
rewrites data, so there is nothing to reverse.

---

## 11. What is local vs published vs deployed

| | |
| --- | --- |
| Locally fixed and tested | `backend/app/schema.py`, `backend/app/schema_check.py`, `backend/app/db.py`, `backend/tests/test_schema_migrations.py` |
| Published to `main` | commit `ce802ba` |
| Deployed to the stand | **NO** — the stand still serves the pre-fix build |

---

## 12. Owner actions

1. **Deploy** the schema fix (§10) — this is what actually ends the production
   error.
2. **Rebuild `web`** so the nginx change on `main` (CSP `frame-ancestors` instead
   of `X-Frame-Options: DENY`, so the Telegram Mini App can be framed) reaches the
   stand.
3. **Rotate** the secrets listed in §9.6 at a convenient time; the app reads them
   from the environment only, so rotation is a `.env` edit plus `up -d api`.
4. Decide whether to drop the legacy Telegram columns once the backfill has been
   verified on the stand.
