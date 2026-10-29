# Portability audit, 2026-10-29

English version of [../../audit/portability-audit-2026-10-29.md](../../audit/portability-audit-2026-10-29.md)
(the Russian page holds the full detail; this page keeps the same findings and
conclusions).

## What was found

| Area | Finding | Fixed |
| --- | --- | --- |
| Secrets in history | `.env.before-telegram-*` files with `JWT_SECRET`, `POSTGRES_PASSWORD`, `ADMIN_PASSWORD` (demo values) and a `db/auth.sqlite3` dump in old commits | files deleted, history rewritten with `git filter-repo --replace-text`, force-push |
| Lint | no ruff configuration and `make lint` declared as a `.PHONY` target without a recipe, so the target silently did nothing | `ruff.toml` with the explicit rule set `E9`, `F`; real `lint` recipe; 30 findings fixed (unused imports and variables, one forward reference) |
| Dependency drift | dev dependencies given as ranges without a linter pinned | `ruff` added to `requirements-dev.txt` |
| Documentation | Russian only, no PDF | full English set in `docs/en/`, PDF in `docs/pdf/{ru,en}`, parity enforced by `tools/docs_pdf.py --check` |
| Module borrowing | modules existed but there was no "what to take" map | `docs/modules/module-map.md` |

## Keys that still need rotation

`AEZA_ADMIN_PASSWORD`, `AEZA_JWT_SECRET` (if they were ever used outside the demo), plus
any Telegram bot token that lived in the deleted files. Cleaning the history removes the
values from the repository; it does not revoke them.

## What remains open

- Rate limiting is delegated to a proxy by design.
- Several `api` replicas are not supported: the snapshot and Telegram sessions live in the
  process.
- Load testing exists as a script, not as a CI gate.
