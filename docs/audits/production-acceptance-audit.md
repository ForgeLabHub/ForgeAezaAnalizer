# Production acceptance audit — aeza-sentinel.pixel-minds.ru

Date: 2026-10-24. Auditor: OpenHands agent (QA/SRE/security review).
Target: `https://aeza-sentinel.pixel-minds.ru/`.
Repository: `Pixelminds-hub/aeza-analizer`.

Nothing was deployed, pushed, or changed on the server. All production traffic
was read-only and authenticated with the owner-provided demo account.

## 1. Verdict

**The deployed application works.** Login, every page, the customer table with
sorting and search, customer detail, the AI-disabled state, and settings all
behave correctly against the real API. Two genuine layout defects were found in
the browser and fixed in the stylesheet, with a regression test that fails on the
old CSS.

No P0 or P1 defect was found. The confirmed defects are **P2 (layout)**. Several
things could not be verified from outside the server and are marked BLOCKED.

## 2. Version actually verified

| Fact | Value | How |
| --- | --- | --- |
| `origin/main` | `534ca6c2f4c1fd3581f2dfdaeba1991cef61f7b8` | `git ls-remote` |
| Local checkout | `8151b24` on `main`, working tree clean at audit start | `git status` |
| Production OpenAPI paths | **25** | `GET /api/v1/openapi.json` |
| Repo OpenAPI paths | **28** | `backend/openapi.json` |

**Production does not equal `origin/main`.** It is an earlier build: three routes
exist in the repo but return 404 on the stand.

```
missing on production:
  /api/v1/customers/{customer_id}/recommendations
  /api/v1/customers/{customer_id}/recommendations/{code}
  /api/v1/insights/ai
```

Everything else present in the repo's schema is live. The deployed bundle hash
cannot be read from outside, so the exact commit cannot be proven — only the
route set. **This is a limitation, not a conclusion.**

## 3. What was actually run

| Activity | Method |
| --- | --- |
| HTTP probes | `curl` against production |
| Browser testing | Playwright + Chromium, real production DOM, 4 viewports |
| API checks | `curl` with a real JWT from the demo account |
| Local E2E | uvicorn + SQLite on the repo's own code |
| Test suites | pytest (backend + root), `tsc -b`, `npm run build`, docs checker |

## 4. Test results

Legend: **PASS** verified by running; **FAIL** reproduced defect;
**BLOCKED** needs access not available; **NOT TESTED**.

### 4.1 Availability and transport

| Check | Status | Evidence |
| --- | --- | --- |
| HTTPS + valid chain | PASS | `curl -w '%{ssl_verify_result}'` → 0; cert `CN=pixel-minds.ru`, SAN covers the host, expires 2027-01-22 |
| HTTP → HTTPS redirect | PASS | `http://` → 301 |
| `/health` | PASS | 200 `application/json` |
| `/ready` | **FAIL** | 200 but `text/html` — the SPA fallback, not a readiness payload (host nginx lacks `location = /ready`) |
| `/api/v1/docs` | PASS | 200 Swagger UI |
| `/api/v1/openapi.json` | PASS | 200, valid JSON, title `Aéza Analyzer` v2.0.0 |
| Static assets load | PASS | 0 failed requests; 0 console errors |

### 4.2 Security

| Check | Status | Evidence |
| --- | --- | --- |
| Private routes require auth | PASS | `/customers`, `/metrics`, `/model/settings`, `/ai/status`, `/actions`, `/quality` → **401** without a token |
| Login works | PASS | 200 + token; `/auth/me` 200 |
| No stack traces in responses | PASS | error bodies are `{"detail": ...}` only |
| AI disabled does not break analytics | PASS | `/ai/status` → `enabled:false`; all other pages fully functional |
| Secrets in tracked files | PASS | `git ls-files` scan: no token/key patterns |
| **Security headers** | **FAIL** | none present: no HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP |
| **CORS** | **FAIL** | `Access-Control-Allow-Origin: *` for any Origin |
| Login rate limiting | NOT TESTED | deliberately not exercised against production (would lock the demo account) |
| Server internals (perms, firewall, systemd) | BLOCKED | no SSH access |

### 4.3 Browser walkthrough (Playwright, production)

| Check | Status | Evidence |
| --- | --- | --- |
| Login page renders | PASS | email + password + submit present |
| Login succeeds | PASS | redirected to `/`, token in `localStorage`, `/auth/me` 200 |
| Dashboard renders | PASS | 2 509 chars, metrics + priority queue |
| Priority page | PASS | 10 394 chars |
| Customers page | PASS | 3 957 chars, **25 rows** |
| AI page | PASS | 685 chars, shows the disabled state |
| Settings page | PASS | 3 794 chars |
| Data/quality page | PASS | 1 304 chars |
| Customer detail | PASS | 4 034 chars, score + reasons |
| Sort toggles both directions | PASS | first column flips `60…` ↔ `1…` |
| Search filters | PASS | `user-0001` → 1 row |
| Deep link after reload | PASS | `/customers/1` survives a reload |
| No console errors | PASS | 0 |
| No failed requests | PASS | 0 |
| **No horizontal overflow @1440** | PASS | 1440 = 1440 |
| **No horizontal overflow @1024** | **FAIL** → fixed | was 1067 > 1024 |
| **No horizontal overflow @768** | **FAIL** → fixed | was 924 > 768 |
| **No horizontal overflow @390** | **FAIL** → fixed | was 908 > 390 |

Screenshots: not committed. The browser ran headless in a sandbox and the
captures would be the deployed third-party UI; the measurements above are the
durable evidence.

### 4.4 Functional / analytics

| Check | Status | Evidence |
| --- | --- | --- |
| Baseline summary | PASS | 60 customers, `revenueAtRisk` **1453.09 €**, categories low 25 / medium 13 / high 8 / insufficient 5 / n/a 9 |
| Risk score is not a probability | PASS | `model.type = rule_based_weighted`, `calibrated: false`, and the dashboard states this in the UI |
| Customer detail consistency | PASS | `/customers/1` → score 50.0, category medium |
| Weight change recalculates | PASS | local: `expiry_proximity` 3→9 → revenue **5.80 → 7.72 €**, generation 1→2 |
| Settings persist across restart | PASS | after restarting the app, `expiry_proximity = 9.0` |
| `/metrics` agrees with the summary | PASS | `aeza_revenue_at_risk_eur 7.72` matches the API to the cent |
| Money unit | PASS | values are eurocents internally, rendered as EUR with 2 decimals |
| Recommendations route on prod | **FAIL (deploy gap)** | 404 — see §2 |

## 5. Defects found

### D-1 (P2, FIXED) — dashboard and header caused page-level horizontal scroll

**Severity:** P2 — real usability defect on tablets and phones.

**Reproduce:** log in, open `/`, set the viewport to 1024 / 768 / 390 px.

**Expected:** the page fits the viewport; wide tables scroll inside their card.

**Actual:** `document.documentElement.scrollWidth` exceeded the client width
(1067/1024, 924/768, 908/390). Two independent causes:

1. `.grid-2` and the `@media (max-width: 1100px)` rule for `.grid-main`/`.grid-2`
   used a **bare `1fr`** track. A bare `1fr` is `minmax(auto, 1fr)` and cannot
   shrink below its content, so the wide "Ближайшие продления" table forced the
   whole page wider (the card measured **894 px** inside a 390 px viewport).
2. `.app-nav` had no `min-width: 0`, so its nowrap links stopped the header flex
   item from shrinking; `.header-user` ended at **1067 px** at a 1024 px viewport.

**Fix:** `frontend/src/styles.css` — `minmax(0, 1fr)` for the grid tracks and
`min-width: 0; overflow-x: auto` for `.app-nav`.

**Verification:** injecting the rebuilt stylesheet over the live production DOM
gives 1440→1440, 1024→1024, 768→768, 390→390 (all fit).

### D-2 (P2, OPEN — owner action) — `/ready` returns the SPA

`GET /ready` answers 200 with `text/html`. A readiness probe would treat an
unready backend as healthy. Fix belongs in the **host** nginx
(`location = /ready { proxy_pass .../ready; }`); the container's nginx already has
it. Not changed here — it is server configuration, out of scope without approval.

### D-3 (P2, OPEN — owner action) — CORS `*` and no security headers

Production returns `Access-Control-Allow-Origin: *` and none of the security
headers. The repo's Compose default is already narrowed and the container nginx
sets three headers, so this is a **stale deployment**, not a code defect. Fix by
redeploying and setting `AEZA_CORS_ORIGINS` to the real origin.

### D-4 (P2, OPEN — owner action) — production is an older build

Three routes present in `origin/main` are absent on the stand (§2). Either the
stand was never updated past an earlier commit, or it is built from a different
ref. Owner should confirm which commit is deployed.

## 6. Automated test results

| Command | Result | Exit |
| --- | --- | --- |
| `cd backend && python -m pytest tests/ -q` | **315 passed** | 0 |
| `python -m pytest tests/ -q` (root) | **69 passed** | 0 |
| `cd frontend && npx tsc -b` | no errors | 0 |
| `cd frontend && npm run build` | built | 0 |
| `python backend/scripts/check_docs.py` | 4/4 ok | 0 |
| `docker compose config` | valid | 0 |

Backend count rose from 312 to 315: three new layout regression tests
(`backend/tests/test_layout_css.py`).

## 7. Fixes applied

| File | Change | Regression test |
| --- | --- | --- |
| `frontend/src/styles.css` | `minmax(0, 1fr)` grid tracks; `.app-nav { min-width: 0; overflow-x: auto }` | `backend/tests/test_layout_css.py` (3 tests) |

The layout test fails on the old CSS (`1fr 1fr`) and passes on the fix — verified
by temporarily reverting the rule. It reads the real stylesheet, needs no browser,
and catches the exact defect class.

**Nothing was committed or pushed.** Changes are in the working tree only, pending
the owner's approval (the push is also blocked — see §9).

## 8. Ratings

| Area | Rating | Basis |
| --- | --- | --- |
| Functionality | **Good** | every page and core flow works against the real API |
| Analytics correctness | **Good** | control values reproduce; weights recalculate; metrics agree to the cent; the model is honestly labelled non-probabilistic |
| Security | **Fair** | auth enforced everywhere, no leaks, no stack traces — but CORS `*`, no security headers, and login throttling untested |
| Reliability | **Fair** | no console/network errors; `/ready` is misleading; production is behind the repo |
| UX | **Good after fix** | clear Russian UI, good error states; horizontal scroll fixed at 4 viewports |
| Deployment hygiene | **Needs work** | stand lags the repo by three routes; headers/CORS not applied |

## 9. Blocked / not tested

| Item | Status | Why |
| --- | --- | --- |
| Exact deployed commit | BLOCKED | no build hash exposed; only the route set is comparable |
| Server internals (systemd, nginx, file perms, backups, real secrets) | BLOCKED | no SSH access |
| Login rate limiting on production | NOT TESTED | would lock the shared demo account |
| Docker image build / cold `compose up` | BLOCKED | the sandbox Docker daemon cannot start |
| AI answer quality on production | NOT TESTED | AI is disabled on the stand (`AEZA_AI_ENABLED=0`) |
| Load / soak testing | NOT TESTED | out of scope; production load tests are prohibited |
| Postgres as the live store | NOT TESTED | production DB is unreachable; local runs used SQLite |

## 10. Owner actions

1. **Deploy the current `main`** so the three missing routes appear, then re-run
   the checks in §4.3.
2. **Fix `/ready`** on the host nginx (D-2).
3. **Set `AEZA_CORS_ORIGINS`** to `https://aeza-sentinel.pixel-minds.ru` and add
   the security headers on the host nginx (D-3).
4. **Approve the layout fix** in `frontend/src/styles.css` so it can be committed
   and shipped.
5. **Unblock the push**: the pushing account needs `Contents: write` on
   `Pixelminds-hub/aeza-analizer` (see `docs/audits/ai-release-gate.md` §8).
6. Decide whether the demo should show the **60/115/285 seed** currently on the
   stand or the official organiser set (10/30/100, control values 71.4 / 5.80 €).
   The stand shows the former; the numbers differ.
