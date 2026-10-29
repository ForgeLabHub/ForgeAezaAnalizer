# Module map: what to borrow for another project

English version of [../../modules/module-map.md](../../modules/module-map.md).

The table answers "what to take if I need X": the minimal set of files, the dependencies,
and what has to be replaced.

| Need | Files to take | External dependencies | Replace |
| --- | --- | --- | --- |
| Risk and revenue computation without I/O | `backend/app/domain/` (`risk.py`, `revenue.py`, `money.py`, `provenance.py`) | — | the factor set and the rules |
| Money without float | `backend/app/domain/money.py` | — | currency and precision |
| Provenance of numbers | `backend/app/domain/provenance.py` | — | the source-reference format |
| Schema application and migrations | `backend/app/schema.py` | SQLAlchemy | the migration registry |
| JWT authentication in a separate database | `backend/auth/`, `backend/auth_schema.sql` | `PyJWT[crypto]` | tables and roles |
| A tool layer for LLMs | `backend/app/ai/tools/` | `httpx` | the tools themselves |
| An LLM provider with a mock implementation | `backend/app/ai/providers/` | `httpx` | the call and the response parsing |
| Prometheus metrics per route | `backend/app/metrics.py` | `prometheus_client` | the metric list |
| Token-protected snapshot ingestion | `backend/app/api/routes_source.py` | FastAPI | the snapshot format |
| Adapters for external channels | `backend/app/integrations/`, `backend/app/telegram/` | SMTP, Telegram API | the providers |

## Transfer rules

1. The domain knows nothing about HTTP, databases or the network — it can be taken whole
   and tested without containers.
2. Adapters (`providers`, `integrations`) hide an external system behind an interface: the
   implementation is replaced, not the calling code.
3. Tests are part of the module: domain → `backend/tests/test_domain.py`, auth →
   `tests/test_auth.py`, AI → `backend/tests/test_ai.py`.
4. Configuration goes through `backend/app/config.py` (`Settings`) only, with safe
   defaults.

## What is not here

- No ORM domain models: data is read from a snapshot, not row by row from tables.
- No task queue: background recalculations live in the process.
