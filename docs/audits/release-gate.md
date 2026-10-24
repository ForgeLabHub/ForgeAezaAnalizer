# Release gate

Date: 2026-10-24. Branch under review: `feat/deployment-readiness`.
Companion documents: `docs/audits/final-project-completion.md`,
`docs/audits/production-readiness-audit.md`.

Rule for this document: **every value comes from a file or a command.** Anything
not verified is written as `UNKNOWN` with the exact command that would resolve
it. No environment value, backup path, systemd unit or migration order is
invented.

## 1. Gate table

| Проверка | Текущее состояние | Доказательство | Блокер | Ответственный | Безопасный следующий шаг |
| --- | --- | --- | --- | --- | --- |
| Backend tests | PASS (210) | `cd backend && python -m pytest tests/ -q` → `210 passed` | — | — | — |
| Root tests | PASS (69) | `python -m pytest tests/ -q` → `69 passed` | — | — | — |
| Frontend typecheck | PASS | `cd frontend && npx tsc -b` → exit 0 | — | — | — |
| Frontend build | PASS | `npm run build` → exit 0 | — | — | — |
| Docs consistency | PASS | `python backend/scripts/check_docs.py` → 4/4 ok | — | — | — |
| Control values | PASS | engine → 71.4 / 5.80 EUR / 17.03 EUR / 3-3-4 | — | — | — |
| Compose config valid | PASS | `docker compose config` → exit 0, 3 services | — | — | — |
| Cold `compose up --build` | NOT VERIFIED | daemon down; stale `dockerd` PID 3542 + running managed `containerd` (PID 3569) | sandbox cannot restart Docker | owner | run on a host with a working Docker daemon (§5) |
| Runtime DB untracked | PASS | `git ls-files db/` → only `analytics_seed.sql`, `schema.sql` | — | — | — |
| No secrets in tracked files | PASS | `git ls-files` scan; `check_docs.py` secret check | — | — | — |
| Clean history branch | PASS (prepared, not promoted) | `feat/deployment-readiness-clean`, 0 `openhands` trailers, identical tree | parallel session active | owner | see §7 |
| Production reachable | PASS | `https://aeza-sentinel.pixel-minds.ru/` → 200, TLS valid to 2027-01-22 | — | — | — |
| Production runs this branch | **NO** | prod OpenAPI = 18 paths, `recommendations` absent | not deployed | owner | deploy after review (§5) |
| `/ready` on production | FAIL (returns SPA HTML) | `curl /ready` → `text/html` | host nginx lacks `location = /ready` | owner | §6.5 |
| Production CORS | FAIL (`*`) | `OPTIONS` with foreign Origin → `access-control-allow-origin: *` | not redeployed; compose now defaults to one origin | owner | set `AEZA_CORS_ORIGINS` on deploy |
| Production security headers | FAIL (none) | `curl -D-` shows no HSTS/nosniff/X-Frame/Referrer | host nginx not updated | owner | §6.5 |
| Production auth enforced | PASS | `/customers`, `/metrics`, `/model/settings` → 401 | — | — | — |
| VM internals (systemd, nginx, perms, backups) | NOT VERIFIED | no SSH; `~/.ssh` absent | no host access | owner | §6.1–6.4 |

## 2. Proven ready

- Calculations reproduce exactly on the organiser dataset (71.4 / 5.80 EUR).
- 279 tests pass; frontend builds; docs consistency passes.
- Compose configuration is valid and self-consistent (3 services, named volume
  `aeza_auth`, ports 8000/8080).
- Auth is enforced on every data route, and the two new hardening controls
  (fail-closed secret, login throttle) are covered by regression tests.
- The runtime SQLite store is out of Git and moved to a named volume.

## 3. Verified locally only

- The browser walkthrough (login → dashboard → customers → detail → settings →
  what-if) against a local API on SQLite.
- The corrected README/runbook launch command (`main:app` from the repo root).
- Playbook status writes (200 / 404 / 422) and persistence.
- That the compose **file** is valid — not that the images build in this sandbox.

## 4. Must be verified on production

1. That the deployed image actually contains this branch (`git rev-parse` of the
   deployed checkout, or the OpenAPI path count ≥ 20).
2. Postgres schema after deploy: the new table
   `analyzer_recommendation_status` exists and the app starts cleanly.
3. `/ready` returns JSON, CORS is narrowed, security headers are present.
4. Auth still returns 401 on private routes and login works with the real
   `AEZA_ADMIN_PASSWORD`.
5. `/metrics` matches the summary (money estimate and risk counts agree).
6. **Which dataset the stand serves.** `db/analytics_seed.sql` (the Compose
   initdb script) seeds **60 accounts / 115 services / 285 transactions**, and
   `docs/audits/production-readiness-audit.md` §2 records the live stand
   returning 60 customers with `revenueAtRisk` 1453.09 EUR. This is *not* the
   official organiser set (10/30/100), so the control values (71.4 / 5.80 EUR)
   do **not** appear on the stand. Before a demo, decide deliberately whether to
   keep the richer seed or load `dataset/data.json`, and state which dataset the
   audience is looking at.

## 5. Owner actions (exact, but confirm applicability first)

These commands are **not** verified against the real host; the deploy directory,
service manager and file paths below are `UNKNOWN` and must be read from the
host before running anything.

```bash
# 0. Confirm where the stack actually lives and how it is started. Do not guess.
cd <UNKNOWN_DEPLOY_DIR>
docker compose config | head -5          # must match docker-compose.yml in the repo
systemctl status docker                  # UNKNOWN whether the stack is a unit
```

```bash
# 1. Build and start the reviewed commit (cold build is the step this sandbox could not do).
git fetch --all
git checkout <REVIEWED_COMMIT>           # the tip of feat/deployment-readiness
docker compose build
docker compose up -d
docker compose ps                        # expect three healthy services
```

```bash
# 2. Environment that MUST be set on the host (names from .env.example; values are yours):
#    AEZA_JWT_SECRET           long random, not the compose default
#    AEZA_ADMIN_PASSWORD       real password
#    AEZA_CORS_ORIGINS         https://aeza-sentinel.pixel-minds.ru
#    AEZA_METRICS_TOKEN        optional; without it /metrics needs an analyst session
```

## 6. Owner actions blocked without SSH

### 6.1 Autostart
```bash
systemctl is-enabled docker nginx
docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $(docker compose ps -q api)
```

### 6.2 Ports / nginx
```bash
ss -lntp | grep -E ':(80|443|8000|8080)\b'
nginx -t
grep -R "server_name\|proxy_pass\|location" /etc/nginx/sites-enabled/
```

### 6.3 SQLite permissions
```bash
ls -la <UNKNOWN_DEPLOY_DIR>/db/
ps -o user= -p $(pgrep -f 'uvicorn main:app' | head -1)
# Fix only for the actual process user; never chmod -R 777, never delete the file.
```

### 6.4 Backup and restore check
```bash
# SQLite (auth) — consistent copy, WAL-aware:
docker compose exec -T api python - <<'PY'
import sqlite3
s=sqlite3.connect('/app/db/auth.sqlite3'); d=sqlite3.connect('/tmp/auth.bak')
s.backup(d); d.close(); s.close(); print('ok')
PY
docker compose cp api:/tmp/auth.bak /tmp/auth-$(date +%F).sqlite3
sqlite3 /tmp/auth-$(date +%F).sqlite3 'PRAGMA integrity_check;'   # expect: ok

# Postgres (analytics) — the store the stand actually serves:
docker compose exec -T db pg_dump -U aeza -d aeza > /tmp/aeza-$(date +%F).sql
# Restore check into a scratch database, never over the live one:
docker compose exec -T db createdb -U aeza aeza_restore_check
docker compose exec -T db psql -U aeza -d aeza_restore_check < /tmp/aeza-$(date +%F).sql
docker compose exec -T db psql -U aeza -d aeza_restore_check -c \
  'SELECT (SELECT count(*) FROM accounts), (SELECT count(*) FROM services), (SELECT count(*) FROM transactions);'
docker compose exec -T db dropdb -U aeza aeza_restore_check
```
Backup destination is `UNKNOWN`; keep it off the served tree and out of Git.

### 6.5 Host nginx
```nginx
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
location = /ready { proxy_pass http://<UNKNOWN_API_UPSTREAM>/ready; }
# HSTS only because TLS terminates here:
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```
Then `nginx -t && systemctl reload nginx`.

## 7. Rollback

**Schema compatibility first.** This branch's only schema change is **additive**:
`backend/app/db.py` adds `RecommendationStatusRow`
(`analyzer_recommendation_status`) to `ANALYTICS_TABLES`, created by
`Base.metadata.create_all` at startup. There is **no** `ALTER`/`DROP` and no
migration runner in the stack. Verified facts:

- `backend/migrations/*.sql` is **not mounted or copied anywhere** (`grep -rn
  migrations docker-compose.yml backend/Dockerfile` → no match), so it is not
  part of the Compose runtime.
- The only Postgres initdb script is `db/analytics_seed.sql`
  (`docker-entrypoint-initdb.d/20-analytics-seed.sql`). It creates the
  `analyzer_*` tables with `CREATE TABLE IF NOT EXISTS` and seeds **60 accounts /
  115 services / 285 transactions** — this is why the live stand reports 60
  customers, not the official 10/30/100.

Therefore:

- **Rolling code back to the previous commit is safe for the data**: the extra
  table is ignored by the old code, and no column was removed or retyped.
- **Rolling forward is also safe**: the table is created on first start.
- `docker compose down -v` would **destroy** the Postgres volume and the
  `aeza_auth` volume; on the next start Postgres is re-seeded from
  `db/analytics_seed.sql` (60/115/285), **not** from the organiser dataset, and
  all operator playbook statuses are lost. Do not use `-v` during a rollback.

```bash
# Safe code rollback (keep volumes):
cd <UNKNOWN_DEPLOY_DIR>
git checkout <PREVIOUS_GOOD_COMMIT>
docker compose build && docker compose up -d
# Verify:
curl -s http://127.0.0.1:8000/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/customers   # expect 401
```

Do **not** restore an older Postgres dump over the live database unless the
release wrote data you need to undo; this release writes only
`analyzer_recommendation_status` rows (operator playbook statuses), which are
workflow state, not analytical data.

## 8. Post-deploy verification

```bash
S=https://aeza-sentinel.pixel-minds.ru
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' $S/health          # 200 application/json
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' $S/ready           # 200 application/json (not text/html)
curl -s $S/api/v1/openapi.json | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["paths"]))'  # >= 20
curl -s -o /dev/null -w '%{http_code}\n' $S/api/v1/customers                # 401
curl -s -D- -o /dev/null $S/ | grep -i 'x-content-type-options'             # present
curl -s -D- -o /dev/null -X OPTIONS -H 'Origin: https://evil.example' $S/api/v1/customers | grep -i 'access-control-allow-origin'
```
Then log in through the UI and confirm the dashboard, the customer table sort
and one playbook status write. A mismatch between `/metrics` and the dashboard
summary is the signal that two generations are being served.

## 9. Never do before the owner confirms

- `docker compose down -v`, `docker volume rm`, or deleting `db/postgres` /
  the `aeza_auth` volume.
- `git push --force`, rewriting published history, or pushing to `main`.
- Changing `AEZA_JWT_SECRET` without accepting that all current sessions die.
- Restoring a Postgres dump over the live database.
- Running `backend/migrations/001_schema.down.sql` on production (it drops tables
  and all their rows).
- Editing the host nginx without `nginx -t`.
