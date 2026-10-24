# GitHub repositories found for the Aéza case names

Date: 2026-10-24. Method: GitHub REST search API (authenticated), exact case
names plus `aeza`. Every row was fetched live; nothing here is guessed.

**Read the limits first.** These are repositories the search *returns*, not a
pre-agreed list of 11. The task's "11 repositories" list was not present in the
repository (see `README.md` §Blocker), so it is not reconstructed here. Only
repositories that either (a) name an Aéza case or (b) are part of the same
hackathon cohort are listed. None was integrated; no code was copied.

## 1. `Cricko7/ssh-arena` — the «SSH-арена» case

| Field | Value |
| --- | --- |
| URL | https://github.com/Cricko7/ssh-arena |
| Description | "Кейс от компании aeza" |
| Language | Go |
| Licence | **none declared** |
| Created / last push | 2026-03-20 / 2026-03-22 |
| Size | 123 files |
| CI | yes (`.github/workflows/ci.yml`, `deploy.yml`) |
| Compose | yes (`docker-compose.yml`) |
| Layout | `cmd/` (ssh-server, grpc-game, game-client), `internal/` (64 files), `proto/`, `migrations/`, `events/`, `extensions/` |

**What it is.** A terminal-first multiplayer exchange game server. SSH is used
only to bootstrap a session (first login, account recovery); all gameplay runs
over gRPC with JSON payloads. It has price-time priority order books, a dynamic
price engine, market events, and per-role starting resources.

**Ideas worth taking for our case.**

- *Roles as a first-class config concept* (`config/roles.json`). Our product has
  no user roles at all; if analyst/manager roles are ever needed, a declarative
  role table is the cheap shape.
- *Migration directory as source of truth* (`migrations/`). We already do this
  in `backend/migrations/`; the pattern is confirmed as reasonable.
- *Separating a bootstrap transport from the data plane.* Their SSH-vs-gRPC
  split is the same idea as our nginx→SPA + `/api` split.

**Risks / limits.** No licence means **do not copy code**. Different domain
(games, not churn analytics). Go, not Python. Not an organiser brief — it is one
team's implementation.

**Decision: study only, do not integrate.**

## 2. `yulichump/hackathon-autumn-2026` — sibling hackathon entry

| Field | Value |
| --- | --- |
| URL | https://github.com/yulichump/hackathon-autumn-2026 |
| Description | Team "Собчачка", case "Invoice Keeper — напоминания о регулярных платежах" от Aeza |
| Language | Python |
| Licence | **none declared** |
| Created | 2026-10-23 |
| Layout | `backend/` (33 files), `frontend/` (42 files) |

**What it is.** A different Aéza case from the same «Осень 2026» cohort:
recurring-payment reminders in Telegram. Same problem space (subscriptions,
renewals, customer retention) from the reminder side.

**Ideas worth taking.**

- The split is the same as ours (Python backend + JS frontend), which suggests
  our stack choice is not unusual for this cohort.
- Its reminder-centric framing is a **complement** to our risk scoring: our
  Action Center already produces "what to do" recommendations; a reminder
  channel would be a delivery mechanism, not a new model.

**Risks / limits.** No licence. No CI, no Compose, no tests visible at the top
level — lower engineering maturity than ours. Different case, so its acceptance
criteria do not apply to us.

**Decision: study only; the reminder channel is a possible future feature, not
a requirement.**

## 3. `Unkno394/aeza-intelligence` — behavioural model

| Field | Value |
| --- | --- |
| URL | https://github.com/Unkno394/aeza-intelligence |
| Language | Rust |
| Licence | **none declared** |
| Created / last push | 2026-10-23 / 2026-10-24 |
| Layout | Rust crate + `frontend/`, `docs/`, `Dockerfile`, `docker-compose.yml`, `.env.example` |

**What it is.** An online behavioural model for one customer at a time. Its
README states it adapts Welford embedding, transition graph and LCS ideas from
another project, and that **no training data is required before the first
observation**. Features it names: `server_count`, `monthly_spend`,
`financial_runway_days`, `autorenew_disabled_share`.

**Ideas worth taking — with care.**

- The feature names are a useful vocabulary; `autorenew_disabled_share` and
  `financial_runway_days` are close to our `auto_prolong_disabled` and
  `insufficient_balance` factors, which cross-validates our factor set.
- Online (single-observation) updating is attractive but **cannot be honestly
  adopted here**: our snapshot has no churn labels and no history, so a
  "learned" model would be unvalidatable. Our `docs/DATA_AND_RISK_MODEL.md`
  already states the score is not a probability.

**Risks / limits.** No licence. Rust. Its model quality cannot be assessed from
the README, and it is not an organiser brief.

**Decision: study only. Do not replace the transparent weighted score.**

## 4. Adjacent repositories (not case entries)

These appeared in the `aeza in:name,description` search and are listed only so
the search is auditable. None relates to the churn case.

| Repository | Language | Note |
| --- | --- | --- |
| `Pixelminds-hub/aeza-analizer` | Python/TS | **our own repository** |
| `Vatalone/aeza` | TypeScript | no description |
| `geff1778/Aeza` | — | no description |
| `LerkOFF/invoice-keeper` | Python | "напоминания о регулярных платежах… (хакатон Aeza РнД)" — same theme as #2 |
| `Roman5358008/aeza-vpn-watchdog` | Python | "External VPN monitoring and recovery for AEZA VPS" — ops tooling, unrelated to churn |
| `aezakmi*`, `Aezarph`, etc. | various | name collisions, unrelated |

## Applicability table

| Idea | Source | Benefit to our case | Effort | Risk | Decision |
| --- | --- | --- | --- | --- | --- |
| Declarative role table | `Cricko7/ssh-arena` | would enable analyst/manager roles | M | needs real RBAC on the backend, not just hidden buttons | **Deferred** — no requirement asks for it |
| Bootstrap/transport split | `Cricko7/ssh-arena` | confirms our nginx/API separation | — | — | **Already done** |
| Reminder delivery channel | `yulichump/hackathon-autumn-2026` | would turn recommendations into outreach | M | needs an external channel + consent handling | **Deferred** — not a requirement |
| Feature vocabulary (`financial_runway_days`, `autorenew_disabled_share`) | `Unkno394/aeza-intelligence` | cross-validates our factor set | S | none if used only as naming | **Adopted as naming evidence only** |
| Online adaptive model | `Unkno394/aeza-intelligence` | could adapt over time | L | **unvalidatable without labels**; would break the "not a probability" claim | **Rejected** |

No repository above carries a licence permitting reuse, so none of their code was
copied. The table records analysis, not integration.
