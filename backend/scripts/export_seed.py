"""Export an analytics database into ``db/analytics_seed.sql``.

The Compose stack mounts the seed into Postgres' init directory, so a fresh
volume serves whatever the seed contains.  Keeping the seed in sync with
``dataset/data.json`` by hand is what produced the 60-vs-10 divergence, so the
seed is generated instead: load a snapshot with ``load_snapshot.py``, then dump
that database here.

    python backend/scripts/export_seed.py --database-url sqlite:////tmp/x.db \
        --out db/analytics_seed.sql

CRLF line endings are deliberate: the checked-in seed has used them since it was
first added, and ``git diff`` reports every line as changed otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine, text


TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("analyzer_current", ("id", "generation", "source_version", "model_version")),
    ("analyzer_models", ("version", "created_at", "payload")),
    ("analyzer_sources", ("version", "captured_at", "payload")),
    ("analyzer_analyses", ("generation", "source_version", "model_version", "as_of", "calculated_at", "summary")),
    ("analyzer_observations", ("source_version", "service_id", "previous_status", "status", "observed_at", "previous_observed_at")),
    ("analyzer_audit", ("generation", "actor", "action", "created_at")),
    ("analyzer_customers", ("generation", "customer_id", "email", "risk_score", "risk_category", "balance", "total_replenished", "payload")),
    ("analyzer_service_index", ("generation", "service_id", "customer_id", "status")),
)


JSON_COLUMNS = {"payload", "summary"}

DDL = """BEGIN;
SET TIME ZONE 'UTC';
CREATE TABLE IF NOT EXISTS analyzer_current (
        id SERIAL NOT NULL,
        generation BIGINT NOT NULL,
        source_version BIGINT NOT NULL,
        model_version BIGINT NOT NULL,
        PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS analyzer_models (
        version BIGINT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        payload JSON NOT NULL,
        PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS analyzer_sources (
        version BIGINT NOT NULL,
        captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
        payload JSON NOT NULL,
        PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS analyzer_analyses (
        generation BIGINT NOT NULL,
        source_version BIGINT NOT NULL,
        model_version BIGINT NOT NULL,
        as_of TIMESTAMP WITH TIME ZONE NOT NULL,
        calculated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        summary JSON NOT NULL,
        PRIMARY KEY (generation),
        FOREIGN KEY(source_version) REFERENCES analyzer_sources (version),
        FOREIGN KEY(model_version) REFERENCES analyzer_models (version)
);

CREATE TABLE IF NOT EXISTS analyzer_observations (
        source_version BIGINT NOT NULL,
        service_id BIGINT NOT NULL,
        previous_status VARCHAR(32),
        status VARCHAR(32),
        observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
        previous_observed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (source_version, service_id),
        FOREIGN KEY(source_version) REFERENCES analyzer_sources (version)
);

CREATE TABLE IF NOT EXISTS analyzer_audit (
        generation BIGINT NOT NULL,
        actor VARCHAR(320) NOT NULL,
        action VARCHAR(32) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (generation),
        FOREIGN KEY(generation) REFERENCES analyzer_analyses (generation)
);

CREATE TABLE IF NOT EXISTS analyzer_customers (
        generation BIGINT NOT NULL,
        customer_id BIGINT NOT NULL,
        email VARCHAR(320) NOT NULL,
        risk_score FLOAT,
        risk_category VARCHAR(32) NOT NULL,
        balance BIGINT,
        total_replenished BIGINT,
        payload JSON NOT NULL,
        PRIMARY KEY (generation, customer_id),
        FOREIGN KEY(generation) REFERENCES analyzer_analyses (generation)
);

CREATE TABLE IF NOT EXISTS analyzer_service_index (
        generation BIGINT NOT NULL,
        service_id BIGINT NOT NULL,
        customer_id BIGINT NOT NULL,
        status VARCHAR(32) NOT NULL,
        PRIMARY KEY (generation, service_id),
        FOREIGN KEY(generation) REFERENCES analyzer_analyses (generation)
);

TRUNCATE TABLE "analyzer_current", "analyzer_models", "analyzer_sources", "analyzer_analyses", "analyzer_observations", "analyzer_audit", "analyzer_customers", "analyzer_service_index" RESTART IDENTITY CASCADE;
"""

INDEXES = """CREATE INDEX IF NOT EXISTS analyzer_customers_balance_idx ON analyzer_customers (generation, balance, customer_id);
CREATE INDEX IF NOT EXISTS analyzer_customers_category_idx ON analyzer_customers (generation, risk_category);
CREATE INDEX IF NOT EXISTS analyzer_customers_email_idx ON analyzer_customers (generation, email, customer_id);
CREATE INDEX IF NOT EXISTS analyzer_customers_replenished_idx ON analyzer_customers (generation, total_replenished, customer_id);
CREATE INDEX IF NOT EXISTS analyzer_customers_risk_idx ON analyzer_customers (generation, risk_score, customer_id);
CREATE INDEX IF NOT EXISTS analyzer_service_status_idx ON analyzer_service_index (generation, status, customer_id);
"""


CHUNK = 100


def quote(value, *, as_json: bool = False) -> str:
    if as_json:

        document = json.loads(value) if isinstance(value, str) else value
        literal = "'" + json.dumps(document, ensure_ascii=False, separators=(",", ":")).replace("'", "''") + "'"
        return literal + "::json"
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def read_rows(engine, table: str, columns: tuple[str, ...]):
    statement = text(f'SELECT {", ".join(chr(34) + c + chr(34) for c in columns)} FROM {table}')
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(statement)]


def emit_table(table: str, columns: tuple[str, ...], rows) -> list[str]:
    if not rows:
        return []
    header = f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) VALUES'
    blocks = []
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start:start + CHUNK]
        body = ",\n".join(
            "(" + ", ".join(quote(v, as_json=column in JSON_COLUMNS) for v, column in zip(row, columns)) + ")"
            for row in chunk)
        blocks.append(f"{header}\n{body};")
    return blocks


def build(database_url: str, source_note: str) -> str:
    engine = create_engine(database_url)
    try:
        header = ["-- PostgreSQL analytics seed exported from the loaded snapshot.", f"-- {source_note}"]
        counts = []
        for table, columns in TABLES:
            counts.append(f"{table}={len(read_rows(engine, table, columns))}")
        header.append("-- Row counts: " + ", ".join(counts))
        header.append("-- Generated by backend/scripts/export_seed.py; do not edit by hand.")
        chunks = ["\n".join(header), DDL.rstrip("\n")]
        for table, columns in TABLES:
            chunks.extend(emit_table(table, columns, read_rows(engine, table, columns)))
        chunks.append(INDEXES.rstrip("\n"))
        chunks.append("SELECT setval(pg_get_serial_sequence('analyzer_current','id'),\n"
                      "    (SELECT MAX(id) FROM analyzer_current), true);")
        chunks.append("COMMIT;")
        return "\n\n".join(chunks) + "\n"
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Экспортировать аналитическую БД в SQL-seed для Compose")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--out", default="db/analytics_seed.sql")
    parser.add_argument("--note", default="Contents are whatever snapshot was loaded into the source database.")
    arguments = parser.parse_args()

    document = build(arguments.database_url, arguments.note)
    Path(arguments.out).write_text(document, encoding="utf-8", newline="\r\n")
    print(f"wrote {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
