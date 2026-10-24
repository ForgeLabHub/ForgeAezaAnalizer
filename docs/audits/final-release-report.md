# Final release report

Date: 2026-10-24. Author: release session (OpenHands agent).

Scope: verify the environment, fix the favicon, publish to GitHub, and verify end to end.

Status labels: **VERIFIED** (reproduced here) · **PASSED WITH LIMITATIONS** ·
**BLOCKED** (cannot proceed without something I do not have) · **NOT TESTED** ·
**REQUIRES OWNER APPROVAL**.

---

## 1. Source and result commits

| Item | Value |
| --- | --- |
| Repository | `Pixelminds-hub/aeza-analizer` |
| Working tree | `/workspace/project/471010cbdc59450fa46d59f13f633d76` |
| Branch | `integration/merge-upstream-20261024` |
| Start commit | `dcc3b0d` |
| **Result commit** | **`4d65b99`** |
| `origin/main` at start | `7e8e0d5` |
| `origin/main` now | `93f344b` (moved twice during this work; both integrated) |
| Divergence at end | **9 ahead, 0 behind** — a fast-forward of `main` |
| Working tree | clean, no conflict markers |

Commits added (oldest first):

| Commit | Summary |
| --- | --- |
| `075743f` | Make the backup dump restorable over a live database |
| `66ac658` | Integrate origin/main: durable auth sessions, and repair the merge breakage |
| `dcc3b0d` | Add the final integration report |
| `416c8b1` | Integrate origin/main again: presentation dataset, brand book, robustness fix |
| `4d65b99` | Add favicon regression tests |

(`db3feee`, `61ad6c8`, `8c50faa` came from the prior session on the same branch.)

---

## 2. Environment verification (Stage 0) — VERIFIED

The brief's assumptions held: the branch existed at `dcc3b0d`, the remote was the
Aéza Sentinel repository, and the tree was clean with no Git operation in
progress. `origin/main` had advanced by three commits since the previous report;
those were fetched and integrated rather than assumed absent.

---

## 3. Favicon — VERIFIED

The premise "no favicon" was **wrong, and the real cause was worse**: the file was
present, linked and served `200`, but the artwork was near-white on transparency
(mean RGB 211; most opaque pixels above 240) and therefore invisible on light
browser chrome — measured **15% visible on light, 94% on dark**. It had been
copied from `aeza.ru`, whose own icon sits on a dark header.

The brand book shipped upstream (`Аеза_Гайдбук_2026.pdf`, page 13 «Иконка
приложения») settles the design: the app icon is the `é` symbol in two contrasting
monochrome versions — white on black and black on white. Implemented exactly that:

- `frontend/public/favicon.svg` — both variants, selected by `prefers-color-scheme`
- `frontend/public/favicon.png` (256), `favicon.ico` (16/32/48/64/128/256),
  `apple-touch-icon.png` (180) — the black-on-white variant
- the `é` path is **taken verbatim** from `docs/deck/brand/icon_light.svg`, the
  same path `AezaLogo.tsx` renders, so nothing was redrawn
- the corrupt `aeza_analyzer/static/favicon.ico` (zeroed BMP header) was repaired

**Verified in a real browser** against the live stack: all four assets load
(`favicon.svg` 150×150, `favicon.png` 256×256, `favicon.ico` 256×256,
`apple-touch-icon.png` 180×180); the served PNG is a dark glyph on a light opaque
tile, ~19:1 contrast. Seven regression tests pin this, including one that fails on
the old white-on-transparent asset (proved by constructing that asset synthetically).

Production still serves the old icon: the fix is on this branch, not deployed.

---

## 4. Publication — BLOCKED

**The push was refused.** Both available credentials authenticate as `Pavel1778`,
which is not the repository owner (`Pixelminds-hub`):

```
remote: Permission to Pixelminds-hub/aeza-analizer.git denied to Pavel1778.
fatal: ... The requested URL returned error: 403
```

This is worth stating precisely, because the API misleads: `GET /repos/...`
reports `permissions.push: true` for these tokens, yet the actual `git push`
returns `403`. The API's permission block reflects the authenticated app/token
view, not effective write access to this repository. **A credential with write
access to `Pixelminds-hub/aeza-analizer` is required** — a classic PAT with the
`repo` scope, or a deploy key with write access.

No remote ref, tag or repository setting was modified. No PR was opened, because
there is no branch to open one from.

**Prepared instead**, so the owner can publish in one step:

- `.tmp_local/aeza-integration.bundle` — the complete history, verified with
  `git bundle verify`
- `.tmp_local/PR_BODY.md` — the ready PR description

```bash
git fetch /path/to/aeza-integration.bundle integration/merge-upstream-20261024:integration/merge-upstream-20261024
git push origin integration/merge-upstream-20261024
```

Both files are under `.tmp_local/`, which is gitignored.

---

## 5. Regression and E2E — VERIFIED

| Check | Command | Result |
| --- | --- | --- |
| Backend suite | `python -m pytest backend/tests -q` | **422 passed** |
| Root suite | `python -m pytest tests -q` | **75 passed** |
| Docs gate | `python backend/scripts/check_docs.py` | **4/4 ok** |
| Byte-compile | `python -m compileall -q backend aeza_analyzer core.py main.py` | exit 0 |
| Whitespace | `git diff --check` | clean |
| Frontend build | `npm run build` | 51 modules, built |
| API image | `docker build -f backend/Dockerfile` | built |
| Web image | `docker build -f frontend/Dockerfile` | built |
| Compose valid | `POSTGRES_PASSWORD=… docker compose config` | OK |
| Compose fail-closed | no password | refuses, as intended |

Total: **497 tests**.

**Live E2E on a real three-service stack** (all healthy), not a health check
standing in for a test:

1. login → dashboard renders real analytics
2. customer search → correct match
3. risk explanation → score 71.4, level high, factors and reasons present
4. financials → €5.80 revenue at risk
5. `expiry_proximity` 3.0 → 1.0 → **71.4 → 64.7**, generation 1 → 2
6. automatic recalculation confirmed; an identical patch afterwards did **not**
   advance the generation
7. restored to 3.0 → **71.4**, reset → `isDefault`
8. dataset is the official **10/30/100**, not the presentation snapshot
9. favicon: four assets served and decoded in a real browser

**Production, read-only:** root `200`, `/health` `200`, 35 documented routes,
login `200`, summary generation 1 with 10 customers. No write, migration or destructive operation was performed.

---

## 6. Unresolved and residual risk

| Item | Status |
| --- | --- |
| Push / PR | **BLOCKED** — credential lacks write access to the repository |
| Server deployment of the favicon | **BLOCKED** — no SSH client, key or host access |
| Reboot-survival of the server itself | **NOT TESTED** — needs host access; `restart: unless-stopped` is configured |
| TLS termination and renewal | **NOT TESTED** — host nginx; out of scope without access |
| AI items requiring a live Ollama | **BLOCKED** — no model available here |
| `.dockerignore` | **NOT TESTED** for impact; the build context is still the whole tree |
| 7-character password minimum (upstream) | **REQUIRES OWNER APPROVAL** — permits `1234567` |
| `demo123` live on the public stand | **REQUIRES OWNER APPROVAL** |
| No role model (any account is an administrator) | **REQUIRES OWNER APPROVAL** |
| npm advisories (2 moderate, prod) | **PASSED WITH LIMITATIONS** — need SSR or user-controlled URLs; this is a client-only SPA with internal numeric links |

---

## 7. Exact commands for the blocked steps

**Publish the branch** (needs a credential with write access):

```bash
git fetch /path/to/aeza-integration.bundle \
  integration/merge-upstream-20261024:integration/merge-upstream-20261024
git push origin integration/merge-upstream-20261024
# then open the PR against main using .tmp_local/PR_BODY.md
```

**Deploy to the server** (needs SSH):

```bash
cd /path/to/aeza-analizer && git pull --ff-only
docker compose up -d --build
docker compose ps                       # all three healthy
curl -s localhost:8000/health           # 200
```

**Rollback:**

```bash
git checkout <previous-commit> && docker compose up -d --build
# data is unaffected: it lives in the pg_data and auth_data volumes
# scripts/restore.sh <backup_dir> --yes   # if data must be rolled back too
```

---

## 8. Ready to commit / publish

- **Committed:** all nine commits on `integration/merge-upstream-20261024`; tree clean.
- **Ready to publish:** the branch is a fast-forward of `main`, 497 tests pass,
  docs gate green, both images build, live E2E passed. It is ready to push as soon
  as a credential with write access exists.
- **Requires owner approval:** the password minimum, the demo credential, the role
  model, and the production deployment.
