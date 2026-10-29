# Build and run

English version of [../../BUILD.md](../../BUILD.md).

## Pinned versions

| Tool | Version | Source of truth |
| --- | --- | --- |
| Python | 3.12 | `backend/Dockerfile`, CI |
| Backend dependencies | exact versions | `backend/requirements.lock.txt` |
| Node | 22 | `frontend/Dockerfile`, CI |
| Frontend dependencies | `package-lock.json` | `npm ci` |
| PostgreSQL | 16 | `docker-compose.yml` |

## Level A — source code

```bash
make doctor       # tools, .env, ports
make lint         # ruff with an explicit rule set (see ruff.toml)
make test-backend # domain and API
make test-auth    # the auth module without PostgreSQL
make docs-check
```

## Level B — frontend build

```bash
cd frontend && npm ci && npm run build
```

## Level C — full stack

```bash
cp .env.example .env     # POSTGRES_PASSWORD is mandatory
make compose-up
make smoke-test API_URL=http://localhost:8000
```

## Level D — CI

`ci.yml` runs backend tests, the auth tests, the frontend build, the OpenAPI contract
check, the documentation check and a compose configuration check.
`portability.yml` adds the full-stack scenario: schema on an empty database, an idempotent
restart, backup → restore → smoke test, and a start without optional integrations.

## Level E — documentation as artefacts

```bash
make docs-pdf    # Markdown -> PDF for both languages, output in docs/pdf/
```

`tools/docs_pdf.py --check` (part of `make docs-check`) fails when a document has no
translation or no PDF.
