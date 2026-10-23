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
docs/              DATA_AUDIT.md, SCHEMA_MAPPING.md
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

## Pushing to GitHub — blocked by app installation scope

`git push` to `Pixelminds-hub/aeza-analizer` fails with **403 "Permission to
Pixelminds-hub/aeza-analizer.git denied to Pavel1778"**. This is not a code or
credential-expiry problem; it is an access-scope problem. Do not retry it
endlessly or try to work around it.

Root cause (verified via the API):

- the target repo is owned by the **user** `Pixelminds-hub`;
- the OpenHands GitHub App (`app_slug=openhands-ai`, `contents: write`) is
  installed only on `Pavel1778` (user) and `Pixel-Minds` (organization).
- `Pixelminds-hub` and `Pixel-Minds` are **different accounts** despite the
  similar names, so no installation grant covers the target repo.

Because there is no grant, every write path returns
`Resource not accessible by integration` (403): `git push`, `POST /forks`,
`PUT /contents/...`, `POST /user/repos`, and branch-protection reads.

The token itself is fine — a `git push --dry-run` to `Pavel1778/frog-coder`
succeeds, and `permissions.push: true` in the repo payload reflects the
**user's role**, not the token's granted scopes. Don't be misled by it.

To publish, either install the app on `Pixelminds-hub`, or push manually with a
token that has `contents: write` on that repo. Work is kept committed on local
`main` (fast-forwarded) so it is ready for a single `git push` once access exists.

## Gotchas that already bit us

`from .config import settings` binds the `settings` object; `Settings` reads
env vars lazily (properties) precisely so tests can repoint `AEZA_DATA_DIR`
without reloading modules. Keep it lazy.

Also avoid naming a loop/local variable `service` in API handlers — it shadowed
the analytics service and caused a 500.
