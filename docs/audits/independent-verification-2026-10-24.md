# Independent verification of the external readiness assessment

Date: 2026-10-24. Branch `fix/resolve-main-conflict-markers`, HEAD `61ad6c8`,
plus the working-tree fixes described below. `origin/main` was `40e3247` at the
time of writing.

Method: read the code and the published production surface, then reproduce each
claim in isolation. Nothing destructive was run against production; no secret was
printed. Each finding below is marked:

- **[VERIFIED]** — reproduced with a command; the command and its output are shown.
- **[FALSE]** — the claim does not hold against the current code or production.
- **[OWNER DECISION]** — not a code defect; a choice the project owner must make.

---

## 1. Summary

The external assessment ("68% readiness") is directionally fair about process
maturity, but several of its *specific* technical claims are wrong against the
current tree, and it omits the defects that actually matter. The table separates
them.

| Assessment claim | Verdict | Evidence |
| --- | --- | --- |
| Production sends `Access-Control-Allow-Origin: *` | **[FALSE]** | Production answers `access-control-allow-origin: https://aeza-sentinel.pixel-minds.ru`; the code uses `settings.cors_origins`, never a wildcard. |
| Security headers are missing | **[FALSE]** | Production returns `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` (nginx + app). |
| Retention Playbooks are missing in production | **[FALSE]** | Production OpenAPI lists 35 paths, including `/api/v1/customers/{customer_id}/recommendations` and its `PATCH`. |
| Secrets leaked into Git history are a P0 release blocker | **[OWNER DECISION]** | History holds only demo/placeholder values; see §3. Revocation is a choice, not a code defect. |
| "457 vs 413+71" test counts are inconsistent | **[FALSE]** | 388 backend + 75 root = 463 at HEAD, matching the committed number. Different snapshots, not a contradiction. |
| CSV export of 50k rows is slow / memory-heavy | **[FALSE]** | Already streamed (`StreamingResponse`, `pageSize <= 2000`) since commit `da4f173`. |
| No proven backup/rollback | **[VERIFIED]** | No backup or restore script existed. Fixed: `scripts/backup.sh`, `scripts/restore.sh`. |

The defects the assessment did not surface, all reproduced in §2, are the real
findings: a fabricated number that survived the AI safety check while the answer
claimed it had been removed, a notification dedupe key that suppressed every
alert after the first, a recalculation loop that grew the analysis tables without
any input change, and a diagnostics route that exposed every linked chat.

---

## 2. Verified defects and fixes

### A-1 (high) — an invented number survived the AI repair

**[VERIFIED]** `enforce()` stripped ungrounded numbers from `summary`, `facts`,
`recommendations` and `factor_explanation`, but **not** `limitations`, and then
appended a notice saying unconfirmed numbers had been removed.

```
before:  limitations = "прогноз 99.9"
         "99.9" in cleaned.limitations -> True
after:   limitations = "Ответ прошёл автоматическую проверку: ... удалены. ..."
         "99.9" in cleaned.limitations -> False
```

Impact: the user was served the fabrication *and* a false assurance about it.

Fix: `backend/app/ai/safety.py` — `limitations` is stripped like the other
fields. Test: `test_enforce_removes_invented_number_from_limitations`.

### A-2 (medium) — citations were not checked for invented numbers

**[VERIFIED]** `check_numbers` ignored `citations`, which the UI shows as the
source of a claim. Fix: citations are checked, and an offending citation is
dropped. Tests: `test_invented_number_in_a_citation_is_detected_and_dropped`,
`test_grounded_citation_is_kept`.

### T-1 (high) — every alert after the first was suppressed

**[VERIFIED]** `build_events` read `summary["generation"]`, but the engine nests it
under `summary["version"]`.

```
before:  dedupe_key = "high_risk:None:1"   # identical across generations
after:   dedupe_key = "high_risk:3:1"      # distinct per generation
```

Impact: once the first alert was delivered, the key never changed, so no later
alert for that customer could ever be sent.

Fix: `notifications._generation_of(analysis)` reads both shapes. Test:
`test_generation_is_read_from_the_version_block`.

### T-2 (medium) — every high-risk customer re-alerted on every run

**[VERIFIED]** `dispatch_notifications` never passed `previous`, so the event
builder could not tell a transition from a steady state and treated every
high-risk customer as newly high-risk.

Fix: the callers pass the previously published analysis, read from storage via
`Storage.published_analysis()` (not recomputed — see the idempotency note in
`AGENTS.md`). Tests: `test_standing_high_risk_does_not_re_alert_when_previous_is_passed`.

### T-3 / C-1 (medium) — recalculation grew the tables with no change

**[VERIFIED]** `Core.update(recalculate=True)` entered the publication branch
unconditionally.

```
before:  gen after import 1 | after 3 no-op ticks 4   # +1 per tick
after:   gen after import 1 | after 3 no-op ticks 1
```

Impact: `generation` was a tick counter, `analyzer_analyses` and
`analyzer_customers` grew by one row per customer per minute, and any
generation-based dedupe key looked "new" forever.

Fix: `Core.update(force=...)` replaced `recalculate=...`. A plain tick returns
`previous`; `force=True` is used only for the engine-version upgrade in
`main.initialize`, where the inputs are identical but the result must change.
Tests: `test_a_plain_tick_does_not_publish_a_new_generation`,
`test_force_publishes_without_an_input_change`.

### T-4 (medium) — a rate-limited event was lost permanently

**[VERIFIED]** the claim row was written before the rate-limit check and left as
`rate_limited`, so a retry with the same key never sent.

```
before:  rows after rate-limit = [('A','sent'), ('B','rate_limited')]
         retry B -> False   # lost
after:   rows after rate-limit = [('A','sent')]        # claim released
         retry B after the window -> True              # delivered
```

Fix: `TelegramService._release()` drops the claim when no attempt was made.
Test: `test_rate_limited_event_is_not_lost`.

### T-6 (medium) — diagnostics exposed every linked chat

**[VERIFIED]** `deliveries()` returned rows for all chats and the route only
required authentication, so any analyst could read every `chatId` and delivery
history.

Fix: `deliveries(chat_id=...)` and the route scopes the result to the caller's own
chat; an unlinked caller sees none. Test:
`test_deliveries_can_be_scoped_to_one_chat`.

### T-7 (low) — the delivery table was never pruned

**[VERIFIED]** `purge_old_deliveries()` was defined but never called, so the table
grew without bound. Fix: it runs on the periodic digest tick. Test:
`test_old_deliveries_are_purged`.

### Operations — no backup or restore existed

**[VERIFIED]** only prose in `docs/DEPLOYMENT_PART_B.md`. Fix: `scripts/backup.sh`
(`pg_dump` plus the SQLite online-backup API for `auth.sqlite3`) and
`scripts/restore.sh` (refuses to run without `--yes`, removes the `-wal`/`-shm`
sidecars before replacing the auth file). `backups/` is gitignored. Tests:
`backend/tests/test_ops_scripts.py`.

---

## 3. Secrets in history — what is actually there

**[VERIFIED]** the only credential-bearing files in history are `.env.bak` and
`.env.before-telegram-20261024-071249` (commit `1fae9e1`), and one historical
`db/auth.sqlite3` blob.

```
.env.before-telegram-...:
  AEZA_ADMIN_PASSWORD=demo123
  AEZA_JWT_SECRET=change-me-in-production
  POSTGRES_PASSWORD=aeza
auth.sqlite3 -> analyzer_users: analyst@aeza.test / pbkdf2_sha256$600000$...
```

- `demo123` is the **documented demo password** (README, `docs/PROVENANCE_AUDIT.md`),
  and it does still authenticate against production. It is a demo credential by
  design, not a leaked production secret.
- `change-me-in-production` is a placeholder, and nothing reads `AEZA_JWT_SECRET`
  or `AEZA_ADMIN_*` any more (authentication moved to `backend/auth/`).
- A full-history scan for private keys, `ghp_`/`github_pat_`, `sk-`, `AKIA`,
  Slack and Telegram bot-token patterns returned **no hits**.

**[OWNER DECISION]** rewriting published history is destructive and shared (`main`
has 40+ commits from other authors). The demo password should be rotated on the
public stand if the stand is meant to hold anything but the synthetic dataset.
That is an operator action, not a code change.

---

## 4. What remains an owner decision, not a defect

- **Public registration (R-1).** The product is closed: the first account is
  created with `python -m backend.users create`. Opening `POST /auth/register`
  would expose customer data to anyone. Recommend keeping it closed and recording
  the choice.
- **Argon2id vs scrypt (R-2).** scrypt at n=131072 is not weaker; switching is a
  preference, and adds a dependency.
- **`context.facts` returned to the client (A-3).** The same data is already
  available through `/customers/{id}` to the same authenticated user; returning it
  again is a duplication, not an exposure. Confirm the intent.
- **Roles.** There are none: any authenticated account is an administrator. The
  Telegram diagnostics leak (T-6) was the one place that turned into a real
  exposure, now scoped. A role model is a product decision.

---

## 5. Verification

```
backend/tests + tests   ->  480 passed  (463 before, 17 added)
check_docs.py           ->  4/4 ok
frontend `npm run build`->  built in 1.04s
production              ->  HTTP 200, 35 routes, CORS restricted, headers present
```

No production configuration, secret, DNS record or TLS certificate was changed.
