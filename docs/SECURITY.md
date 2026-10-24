# Security

Scope: the shipped product (`backend/app/` + `frontend/`) and its deployment.
Findings with raw evidence live in `docs/audits/security-audit.md`.

## Trust boundaries

| Source | Trust | Handling |
| --- | --- | --- |
| Organiser archive `датасет.zip` | **untrusted** | safe extraction + per-record validation |
| HTTP requests | **untrusted** | Pydantic validation, bounded query parameters |
| SQLite auth store | local | created at boot, never committed (see below) |
| Postgres analytics store | local | reached over the Compose network |

## Authentication and authorisation

- Login is `email` + password (`POST /api/v1/auth/login`). Passwords are stored
  as **PBKDF2-HMAC-SHA256** with a per-user 16-byte salt; the plaintext is never
  stored or logged.
- Access tokens are **JWT HS256** with the algorithm pinned
  (`algorithms=["HS256"]`), which blocks the `alg=none` class of attack. `exp`,
  `sub`, `iat` and `jti` are required; the `jti` must match a live server-side
  session row, so logout genuinely revokes the token.
- Token lifetime is bounded to `1..1440` minutes (`AEZA_TOKEN_TTL_MINUTES`).
- **Every** data route requires a bearer token: `/api/v1/customers`,
  `/customers/{id}`, `/analytics/summary`, `/model/settings`,
  `/source/snapshot`, `/quality`, `/priority`, `/scenarios/compare`,
  `/export/customers.csv` and `/metrics` all answer **401** without one.
- There is no role model. The product has a single analyst role; every
  authenticated user can read and change settings. This is a deliberate scope
  decision, recorded here so it is not mistaken for RBAC.

## Login throttling

- `LoginThrottle` (`backend/app/auth/security.py`) keeps a sliding window of
  failed attempts keyed by `email|client`. Past the budget the API answers
  **429** with `Retry-After`.
- Defaults: `AEZA_LOGIN_MAX_ATTEMPTS=10`, `AEZA_LOGIN_WINDOW_SECONDS=300`.
  A successful login clears the counter; the correct password cannot bypass an
  active lockout.
- Limitation: the counter is **per process**. A multi-worker deployment would
  need a shared store (Redis). The reference deployment runs one worker.

## Secrets

- `AEZA_ALLOW_DEV_SECRET` defaults to **`0`**: without a real `AEZA_JWT_SECRET`
  the app refuses to start rather than inventing a throwaway key. Local
  development opts in explicitly with `=1`.
- With `AEZA_ALLOW_DEV_SECRET=0`, `AEZA_ADMIN_PASSWORD` is also required, so a
  shared environment cannot boot with a blank admin password.
- No secret value is committed. `.gitignore` excludes `.env`, `data/`,
  `*.sqlite*`, `db/auth.sqlite3*`.
- The SQLite auth store (`db/auth.sqlite3`) is **not tracked**. It holds password
  hashes and live session rows, so it lives in a named Docker volume
  (`aeza_auth`) in the Compose stack and is recreated empty on first boot.

## Transport and headers

- TLS is terminated by the host nginx; the Compose nginx is HTTP-only and
  therefore deliberately does **not** set HSTS (a browser only honours HSTS over
  HTTPS). It does set `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
  including on `/assets/`.
- API responses carry `Cache-Control: no-store`.
- CSP is **not** set. Introducing it needs a policy compatible with the current
  frontend (inline theme bootstrap in `index.html`, Google Fonts); that is a
  separate, verified change, not a blanket add.
- CORS defaults to the local dev origins. The live stand still returns
  `Access-Control-Allow-Origin: *` because it has not been redeployed from this
  branch; set `AEZA_CORS_ORIGINS` to the real UI origin on the server.

## Input validation and injection

- All request bodies and query parameters are validated by Pydantic; out-of-range
  and unknown fields are rejected with **422**.
- Snapshot import validates every record against the source contract and applies
  the whole snapshot atomically — a rejected import leaves the previous dataset
  untouched.
- Database access goes through SQLAlchemy `select`/ORM expressions. There is no
  string-concatenated SQL.
- Archive extraction rejects path traversal, absolute paths, symlinks, device
  and FIFO members, duplicate names, zip bombs (compression ratio) and oversized
  archives. Nested archives are not extracted and executables are never run.
- CSV export is guarded against **formula injection**: a cell starting with
  `= + - @ \t \r` is prefixed with an apostrophe.

## Error handling and data exposure

- Errors return a generic `{"detail": ...}` body with the correct status
  (401/404/409/422/429/500/502/503). Stack traces are never returned.
- Metrics are aggregate only: no email, customer id or other high-cardinality
  label appears in `/metrics`, and the payload contains no `@`.

## Not verified (no SSH access to the production VM)

- Filesystem permissions on the SQLite store and the `.env` file.
- Firewall rules and exposed ports.
- Whether the real `AEZA_JWT_SECRET` is strong and rotated.
- Absence of secrets in host nginx config and shell history.

Exact commands for the owner are in
`docs/audits/production-readiness-audit.md` §7.

## Dependency audit

Dependencies come from PyPI and npm only. `pip-audit` / `npm audit` were **not**
run in this iteration; run them before a public launch.

## Disclaimer

The absence of findings here does **not** prove the system is secure. Only the
areas listed were examined; no penetration test, dependency scan or host
inspection was performed.
