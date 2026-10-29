# Documentation index

English version. The canonical (Russian) set is [../index.md](../index.md); both are kept
in step and both ship as PDF in [../pdf/](../pdf/).

| Question | Document |
| --- | --- |
| Run it from scratch | [BUILD.md](BUILD.md), [DEPLOYMENT_PART_B.md](DEPLOYMENT_PART_B.md) |
| How the application and the scoring work | [PROJECT_GUIDE.md](PROJECT_GUIDE.md), [architecture/system-context.md](architecture/system-context.md) |
| Why the module boundaries are drawn this way | [architecture/system-context.md](architecture/system-context.md) |
| Data and schema application | [database/schema.md](database/schema.md), [database/migrations.md](database/migrations.md) |
| API: conventions and errors | [api/conventions.md](api/conventions.md), `../../backend/openapi.json` |
| What a particular module does / what to borrow | [modules/](modules/) |
| Operations, metrics, upgrades | [operations/deployment.md](operations/deployment.md), [operations/monitoring.md](operations/monitoring.md) |
| Accounts and sign-in | [AUTH_MODULE.md](AUTH_MODULE.md) |
| Telegram Mini App | [TELEGRAM_BOT.md](TELEGRAM_BOT.md) |
| E-mail | [EMAIL.md](EMAIL.md) |
| AI Analyst and the assistant | [AI_ANALYST.md](AI_ANALYST.md), [AI_ASSISTANT.md](AI_ASSISTANT.md) |
| Dataset and snapshot | [../../dataset/README.md](../../dataset/README.md) |
| What proves it works | [verification/matrix.md](verification/matrix.md), CI |
| Code style and lint | [development/code-style.md](development/code-style.md) |
| Gaps found and fixed | [audit/portability-audit-2026-10-29.md](audit/portability-audit-2026-10-29.md) |

## Rules

1. `backend/openapi.json` is **generated** (`make openapi`) and checked in CI
   (`make openapi-check`).
2. `backend/scripts/check_docs.py` verifies live links, that every `AEZA_*` variable
   exists in `.env.example`, that mentioned routes exist, and that no secret-like examples
   are present. `scripts/docs-check.sh` adds structure and module-specification checks.
3. A new module without a specification following
   [modules/module-template.md](modules/module-template.md) is not considered done —
   checked in CI.
4. Any document claiming behaviour must have a row in
   [verification/matrix.md](verification/matrix.md): claim → command → CI.

## Project control

- `forge.sh` / `forge.bat` start, stop, tail logs, run tests, manage the database and
  containers in one command; see the README section.
