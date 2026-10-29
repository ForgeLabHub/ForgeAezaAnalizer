# Verification matrix

English version of [../../verification/matrix.md](../../verification/matrix.md).

| Check | What it proves | Command | CI |
| --- | --- | --- | --- |
| Backend tests | the domain and the API are correct | `make test-backend` | `ci.yml` → `backend` |
| Auth tests without PostgreSQL | the sign-in module is independent of the analytics | `make test-auth` | `ci.yml` → `backend` |
| ruff | static rules are respected (`E9`, `F` with an explicit config) | `make lint` | `ci.yml` → `backend` |
| Frontend dependency check | the UI builds reproducibly | `make test-frontend` | `ci.yml` → `frontend` |
| The API specification matches the code | the documentation does not lie about routes | `make openapi-check` | `portability.yml` → `contract` |
| Specification generation is idempotent | a repeated export does not change the file | `make openapi && git diff --exit-code backend/openapi.json` | `portability.yml` → `contract` |
| The stack is ready before the checks | the smoke test does not race the application | `make wait` | all `portability.yml` jobs |
| The showcase proxies the API | the nginx layer really works, not only the api | `make smoke-test` (checks `:8000` and `:8080`) | `portability.yml` → `compose-smoke` |
| Documentation is consistent | links are alive, variables and routes exist, every document has a translation and a PDF | `make docs-check` | `ci.yml` → `docs`, `portability.yml` → `docs` |
| Compose fails without a secret | the production configuration cannot be empty | `docker compose config` | `ci.yml` → `compose` |
| The full stack comes up | the services really talk to each other | `make compose-up` + `make smoke-test` | `portability.yml` → `compose-smoke` |
| A repeated start is safe | schema application is idempotent | two API starts in a row | `portability.yml` → `upgrade-path` |
| Backup → restore → smoke | data is restored, not only copied | `make backup` → `make restore` → `make smoke-test` | `portability.yml` → `backup-restore` |
| Start without optional integrations | AI, Telegram and e-mail are options, not a start condition | `make compose-up` without them | `portability.yml` → `config-without-secrets` |
| Host check | the environment is suitable before start-up | `make doctor` | locally |

## What is deliberately not checked

- LLM answer quality: only the fact that numbers come from the domain is checked.
- Performance and load (there is `backend/scripts/loadtest.py`, but it is not in CI).
- Several `api` replicas: Telegram session state and the snapshot live in the process.
