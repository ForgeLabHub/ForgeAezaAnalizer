# Final project completion report

Date: 2026-10-24. Branch: `feat/deployment-readiness` (active) and
`feat/deployment-readiness-clean` (trailer-free copy). Repository:
`Pixelminds-hub/aeza-analizer`.

Status vocabulary: **DONE** (done and verified), **PARTIAL**, **BLOCKED**
(needs access or missing source), **NOT DONE**. Nothing below is upgraded from
BLOCKED/PARTIAL to DONE.

## 0. Where the work happened

The session opened in `/workspace/project/5f34fa9a06c7484f9d5bb826bf0afbf0`,
which is an **empty git repository with no commits and no remote**. The real
project is in the sibling directory
`/workspace/project/471010cbdc59450fa46d59f13f633d76`. All work was done there.

A **second agent session was editing the same working tree concurrently**
(conversation `4e1dd0d7…`, implementing the frontend live-refresh and a state
audit). Its changes are present and were verified to build and pass tests
alongside mine; its commits were left intact.

## 1. What was fixed in the backend

| # | Fix | Files | Evidence | Status |
| --- | --- | --- | --- | --- |
| B-1 | `AEZA_ALLOW_DEV_SECRET` defaulted to `True`, so the app minted a throwaway JWT secret instead of refusing to start | `backend/app/config.py` | `Settings()` without a secret now raises `ValueError`; `test_settings_refuse_to_invent_a_secret_by_default` | DONE |
| B-2 | No limit on failed logins | `backend/app/auth/security.py`, `api/routes_auth.py`, `main.py` | live: 10×401 → **429** with `Retry-After: 300`; 5 new tests | DONE |
| B-3 | Compose defaulted CORS to `*` | `docker-compose.yml`, `.env.example` | now `http://localhost:8080`, overridable | DONE (code); stand needs redeploy |
| B-4 | Auth SQLite store tracked in Git (holds password hashes + sessions) | `.gitignore`, `docker-compose.yml` | `git ls-files db/` → only `analytics_seed.sql`, `schema.sql`; store moved to named volume `aeza_auth` | DONE |
| B-5 | Config validation gaps | `backend/app/config.py` | `AEZA_LOGIN_MAX_ATTEMPTS` / `AEZA_LOGIN_WINDOW_SECONDS` bounds checked | DONE |

Not changed, and why: the three coexisting implementations
(`aeza_analyzer/`, `backend/app/`, `backend/auth/`) are independent bodies of
work, not duplicates; none was removed. The per-request recomputation in
`AnalyticsService.analyze_all()` was left as is — caching without a correct
invalidation key would be worse, and it is fine for 10 accounts.

## 2. What was fixed in the frontend (design unchanged)

**No visual, compositional, or structural change was made.** The stack
(React 18 + TypeScript + Vite, one hand-written stylesheet) is untouched, and no
dependency was added or removed. The current interface is recorded in
`docs/audits/frontend-preservation.md` together with the rules for preserving it.

Verified live in a browser against the real API on the 10-customer dataset:
login → dashboard → customers (sort) → customer detail → settings → what-if.
The dashboard rendered 3 high / 3 medium / 4 not-applicable; the what-if
comparison moved customer #10 from 71.4 to 81.8, matching the API.

The live-refresh behaviour (`frontend/src/lib/live.tsx`) was added by the
concurrent session, not by me; it compiles and builds.

Status: **DONE** for verification; **PARTIAL** overall, because there is still
no frontend test runner (`frontend/package.json` has no `test` script), so the
UI is covered by the production build and the manual walkthrough only.

## 3. What was done about "моя роль"

**The phrase does not exist in the project.** A repository-wide search for
«моя роль» / «мою роль» / «моей роли» returns nothing in code, docs, the deck,
or the ТЗ. Two things named "role" do exist:

1. **A team-member role placeholder in the defence deck.**
   `docs/deck/build_deck.py` prints `[ИМЯ УЧАСТНИКА N] · [РОЛЬ УЧАСТНИКА N]`
   (slides 1 and 10), and `aeza_placeholder_checklist.md` lists them as fields
   to fill before the defence. The repository deliberately does **not** invent
   names or roles.
2. **No application role model.** The auth schema has `analyzer_users(email,
   password_hash, created_at)` — no role column — and `backend/auth/` has no
   RBAC either. So "my role" cannot mean a functional role in the product:
   there is exactly one analyst role, and every authenticated user has the same
   rights.

Conclusion recorded rather than guessed: "моя роль" most plausibly refers to the
user's role as a hackathon team member (the deck placeholder), which cannot be
filled from repository data. No interpretation was invented, no unverified
contribution was claimed, and no RBAC was added (nothing in the ТЗ requires it).

Status: **BLOCKED** on missing source (the team's real names/roles are not in the
repository). Ambiguity recorded in `docs/research/README.md`.

## 4. Business logic and calculations

The control values were reproduced from the canonical engine
(`backend/app/domain/module.py:create`) on `dataset/data.json`, not asserted
from memory:

| Value | Expected | Reproduced |
| --- | --- | --- |
| Customer #10 score | ≈ 71.4 | **71.4** |
| `revenueAtRisk` | ≈ €5.80 | **5.80 €** (580 cents) |
| `upcomingRenewals` | — | **17.03 €** |
| Category split | — | **3 high / 3 medium / 4 not_applicable** |
| Weight 3→9 (`expiry_proximity`) | — | score **81.8**, revenue **7.72 €** |

The formula was read from the code, not the docs: `risk_score = 100 × Σ(wᵢfᵢ) /
Σ(wᵢ)` over applicable factors only; customer risk is the max over forecastable
services; `revenue_at_risk = price × score/100` for open services with a positive
price renewing inside the horizon, counted once. Money is integer eurocents
throughout. The model is **not** presented as a probability; `summary.model.calibrated`
is `false`. The full contract is in `docs/DATA_AND_RISK_MODEL.md`.

**Stale-number defect found and fixed in documentation.** The committed defence
deck still shows `73,3 / 100` and `5,74 €`, and its generator docstring falsely
claimed every number came from the product. Both the generator and
`docs/deck/README.md` now state plainly that the slide figures are hardcoded and
were captured under the old weighting (`expiry_proximity` 15.0), so the deck is a
historical artefact until the screenshots are recaptured. The false claim was
removed; the deck itself was **not** silently regenerated with wrong numbers.

Status: **DONE** for the calculations; **PARTIAL** for the deck (needs recaptured
screenshots — a separate task, listed in §12).

## 5. Research: Aéza cases and repositories

**The source list is missing and this is stated, not papered over.** The task
refers to «Логовизор», «SSH-арена», and a list of 11 repositories. A search of
the whole workspace found those strings **only inside the task prompt itself**;
nothing in `docs/`, the ТЗ, or any archive. The ТЗ describes exactly one case:
«Анализатор рисков оттока», хакатон РНД, уровень Middle.

What was actually found through the GitHub REST API (the only endpoint that
returned usable data):

- `Cricko7/ssh-arena` — described as "Кейс от компании aeza". Its README shows
  the case is **SSH as a bootstrap transport for a market-simulation game**, not
  SSH scanning or remote command execution.
- `yulichump/hackathon-autumn-2026` — a sibling «Осень 2026» entry (Invoice
  Keeper, payment reminders).
- `Unkno394/aeza-intelligence` — a Rust online behavioural model, useful only as
  naming cross-validation.
- Adjacent name collisions, listed for auditability.

None carries a licence, so **no code was copied**. Full detail, provenance and
limits: `docs/research/README.md`, `docs/research/aeza-case-analysis.md`,
`docs/research/github-repositories.md`.

Status: **PARTIAL** — case «SSH-арена» has a public third-party implementation
but no organiser brief; case «Логовизор» is **BLOCKED** (0 results everywhere);
the 11-repository list is **BLOCKED** (not in the repository).

## 6. Documentation and README

| Document | Change | Status |
| --- | --- | --- |
| `README.md` | Corrected the backend launch command (`main:app` from the repo root; `app.main:app` from `backend/` fails on a missing `core`), refreshed the config table to the new defaults, recorded the control values, fixed the test counts, repaired a dead `docs/DATA_AUDIT.md` link, rewrote the documentation index | DONE |
| `docs/TESTING.md` | Rewritten with verified counts and the live walkthrough | DONE |
| `docs/SECURITY.md` | Replaced the stale "no authentication / no rate limiting" text with the implemented model | DONE |
| `docs/DATA_AND_RISK_MODEL.md` | New: the money/score contract in one place | DONE |
| `docs/audits/*` | Security, traceability, inventory, frontend-preservation, production-readiness updated | DONE |
| `docs/research/*` | New | DONE |
| `docs/demo.md`, `docs/deck/*` | Stale hostnames, launch command and score corrected; deck divergence stated | DONE |
| Older audits + `docs/REQUIREMENTS_TRACEABILITY.md` | Marked as historical so their old counts/scores are not read as current | DONE |

`backend/scripts/check_docs.py` was added and wired into CI. It fails on broken
relative links, unknown `AEZA_*` variables, routes missing from
`openapi.json`, or a secret-looking example. It currently reports **one** known
failure: the link from `README.md` to this file, which is created last.

Status: **DONE**.

## 7. Files removed, with justification

| Item | Action | Justification |
| --- | --- | --- |
| `db/auth.sqlite3` | untracked + ignored | runtime store holding password hashes and live sessions; must not be versioned |
| `db/auth.sqlite3-shm`, `-wal` | deleted from the tree + ignored | SQLite side files, never belonged in the repo |
| `/tmp/aeza-smoke`, `/tmp/aeza-verify`, `/tmp/readme-check`, `/tmp/aeza-clean.git` | deleted | scratch directories created by this session |

**Nothing else was removed.** In particular the presentations
(`aeza_hackathon_osen_2026.pptx/.pdf`, `aeza_umirhack_defense.pptx/.pdf`),
`docs/deck/shots/`, `docs/deck/brand/`, `ТЗ.pdf`, `датасет.zip`, `dataset/` and
the three code implementations were kept — they are deliverables, source
material, or intentionally preserved work. A full classification is in
`docs/audits/project-inventory.md`.

Status: **DONE**.

## 8. Git history changes and their boundaries

- Commit messages are substantive; my four new commits carry no AI trailer.
- **14 existing local-only commits** carried `Co-authored-by: openhands
  <openhands@all-hands.dev>`. They are **not on any remote** (`git ls-remote`
  shows only `main` and `feat/priority-whatif-integration`; this branch is not
  pushed).
- A trailer-free copy was prepared on the separate branch
  **`feat/deployment-readiness-clean`**, verified to have an **identical tree**
  to the active branch and zero trailers.
- The active branch was **deliberately left intact** (reflog preserved), because
  the concurrent session may still depend on its SHAs. Promoting the clean copy
  is a one-command decision for the owner (§12).
- During preparation, `git filter-branch` was first run against the live
  repository, which rewrote all local and remote-tracking refs. **Every ref was
  restored from `refs/original` and re-verified against `git ls-remote`.** Final
  state: `main` = `d0abced`, `feat/deployment-readiness` = `3340dc6`,
  `origin/main` = `81e28c4` — all correct. This near-miss is recorded rather than
  hidden.
- No force-push, no `reset --hard`, no remote change. Author identities were not
  altered; other contributors' authorship is preserved.

Status: **PARTIAL** — the clean branch exists and is verified, but promoting it
is left to the owner because of the concurrent session.

## 9. Tests run and actual results

| Suite | Command | Result |
| --- | --- | --- |
| Backend | `cd backend && python -m pytest tests/ -q` | **210 passed**, 0 failed |
| Root (part A + auth) | `python -m pytest tests/ -q` | **69 passed**, 0 failed |
| Frontend typecheck | `cd frontend && npx tsc -b` | exit **0** |
| Frontend build | `cd frontend && npm run build` | exit **0** |
| Docs consistency | `python backend/scripts/check_docs.py` | 3/4 checks ok; 1 known (this file) |
| Compose config | `docker compose config` | valid, 3 services |

**279 tests pass.** Note: the suite fails spuriously if `AEZA_*` variables are
exported in the shell; this gotcha is now documented in `AGENTS.md`.

Not run, and stated as such: a cold `docker compose up --build` (the sandbox's
Docker daemon cannot be restarted — a stale `dockerd` plus an already-running
managed `containerd`), and PostgreSQL as the live store (SQLite was used).

## 10. Release-candidate commit

| Branch | Commit | Tree |
| --- | --- | --- |
| `feat/deployment-readiness` (active) | `3340dc6` | `7fd7a7a` |
| `feat/deployment-readiness-clean` (trailer-free) | `7f8c4e2` | `7fd7a7a` |

Both trees are byte-identical.

## 11. Push and deploy

- **Push: NOT DONE.** No commit was pushed. This was not requested, and the
  repository owner differs from the pushing identity (recorded in `AGENTS.md`).
- **Deploy: NOT DONE.** The live stand was verified read-only and is **unchanged**:
  `https://aeza-sentinel.pixel-minds.ru/` answers 200 with a valid Let's Encrypt
  certificate (expires 2027-01-22), but it still runs `origin/main` — 18 OpenAPI
  paths, no playbook routes (`/api/v1/customers/1/recommendations` → 404),
  `/ready` proxied to the SPA as HTML, CORS `*`, and no security headers. It does
  **not** contain this iteration's fixes. No irreversible action was taken.

## 12. Blockers, residual risks, and owner actions

| Item | Status | Owner action |
| --- | --- | --- |
| Production VM internals (systemd, host nginx, file ownership, backups, real secret) | BLOCKED | run the commands in `docs/audits/production-readiness-audit.md` §7 |
| Deploy this branch to the stand | NOT DONE | build and deploy the verified commit, then re-run the smoke checks |
| CORS `*` and security headers on the stand | BLOCKED on redeploy | after redeploy set `AEZA_CORS_ORIGINS` and add the nginx headers |
| Promote the trailer-free history | PARTIAL | `git checkout feat/deployment-readiness-clean` and continue there, or leave as is |
| Deck screenshots show old numbers | PARTIAL | recapture `docs/deck/shots/` on the current engine, then rebuild the decks |
| Frontend test runner | PARTIAL | add vitest + a `test` script; today only the build and the manual walkthrough cover the UI |
| Login throttle is per process | residual risk | move the counter to a shared store if the API is ever scaled past one worker |
| `AEZA_LOGIN_MAX_ATTEMPTS` / `AEZA_LOGIN_WINDOW_SECONDS`, `withdrawBalance` divergence | residual risk | the `balance` vs `withdrawBalance` choice is invisible on this dataset but would matter on one with a large price against a drained `withdrawBalance` (`AGENTS.md`) |
| «Логовизор» case and the 11-repository list | BLOCKED | supply the organiser materials; nothing was invented in their place |

## 13. Honest summary

The product works, the required calculations reproduce exactly, the security
defaults are now fail-closed, the documentation matches the code, the repository
is clean, and 279 tests pass. What remains is either **outside this environment**
(SSH to the VM, a Docker daemon that can restart, the organiser's research
materials) or **an owner decision** (push, deploy, promote the cleaned history).
None of those is claimed as done.
