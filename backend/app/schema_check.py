"""Report schema drift between the ORM models and a live database.

Run before a deployment to see whether the database the app will start against
matches the models, without changing anything:

    python -m backend.app.schema_check
    python -m backend.app.schema_check --url postgresql+psycopg://user:pw@host/db

Exit code 1 means drift was found (missing tables or columns), so a deploy that
expects them would fail at runtime. Exit code 0 means the database matches.

It is read-only: it never alters the database. The runtime reconciliation in
``backend/app/schema.py`` is what actually fixes drift; this is the check that
tells an operator *before* the release.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import inspect

from backend.app.db import ANALYTICS_TABLES, Database
from backend.app.config import Settings


def drift(engine) -> dict[str, list[str]]:
    """Return ``{"missingTables": [...], "missingColumns": [...]}``."""

    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    for table in ANALYTICS_TABLES:
        if table.name not in present:
            missing_tables.append(table.name)
            continue
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in columns:
                missing_columns.append(f"{table.name}.{column.name}")
    return {"missingTables": sorted(missing_tables), "missingColumns": sorted(missing_columns)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report ORM/database schema drift (read-only)")
    parser.add_argument("--url", default=None, help="database URL; defaults to AEZA_DATABASE_URL")
    arguments = parser.parse_args(argv)

    url = arguments.url or Settings().database_url

    print("Checking schema drift against the configured database ...")
    result = drift(Database(url).engine)
    if not result["missingTables"] and not result["missingColumns"]:
        print("ok    no drift: every model table and column is present")
        return 0
    print(f"FAIL  missing tables: {len(result['missingTables'])}")
    for name in result["missingTables"]:
        print(f"        {name}")
    print(f"FAIL  missing columns: {len(result['missingColumns'])}")
    for name in result["missingColumns"]:
        print(f"        {name}")
    print("A release that reads these will fail. The app reconciles columns on start;")
    print("a missing table is created by initialize(). Review before deploying.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
