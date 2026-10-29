# Data schema

English version of [../../database/schema.md](../../database/schema.md).

Two databases (see [architecture/system-context.md](../architecture/system-context.md)):

| Database | Purpose | Where it is described |
| --- | --- | --- |
| PostgreSQL | domain data and analytics aggregates | `db/schema.sql`, `backend/migrations/*.sql`, `backend/app/schema.py` |
| SQLite | accounts, sessions, keys | `backend/auth_schema.sql` (`db/schema.sql` is copied into the image as the auth schema) |

## Data ownership

| Domain | Writer | Reader |
| --- | --- | --- |
| Source snapshot (accounts, services, transactions) | snapshot import and `AEZA_SNAPSHOT_PATH` | analytics domain |
| Aggregates and risk metrics | analytics domain (`backend/app/domain/*`) | API, export, AI tools |
| AI insights | the AI service (after tool validation) | API, reports |
| Actions and scenarios | `domain/actions.py`, `domain/scenarios` through the API | API, AI tools |
| Users and sessions | `backend/auth` (SQLite) | API |

## Rules

1. **Money is integer minor units plus a currency.** Arithmetic lives in
   `backend/app/domain/money.py`; `float` is forbidden in revenue calculations.
2. **Provenance is mandatory.** Every aggregate knows which snapshot it came from
   (`domain/provenance.py`), otherwise a number cannot be explained.
3. **The risk score is explainable:** the contribution of every factor is stored, not just
   the total.
4. **The snapshot is replaced as a whole** (`PUT /api/v1/source/snapshot`): it is a
   re-indexing operation, not a partial `UPDATE` of arbitrary rows.

## Verification

- Applying the schema to an empty database: `make compose-up` → the API start runs
  `schema.ensure_schema()` (column reconciliation plus the migration registry).
- Repeated start: the `schema_migrations` registry prevents a second application.
- Data: `python backend/scripts/load_snapshot.py` and `backend/tests/test_api.py`.
