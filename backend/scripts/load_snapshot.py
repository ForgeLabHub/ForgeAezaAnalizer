#!/usr/bin/env python3
"""Load a source snapshot into the application database.

Usage:
    python scripts/load_snapshot.py [path/to/snapshot.json]

Validates the whole file first and replaces the dataset atomically.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db, session_scope  # noqa: E402
from app.domain.importer import import_snapshot, parse_snapshot  # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/snapshot.json"
    if not os.path.exists(path):
        print(f"snapshot not found: {path}", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    snapshot = parse_snapshot(payload)
    init_db()
    with session_scope() as session:
        result = import_snapshot(session, snapshot)
    print(
        f"imported accounts={result.accounts} services={result.services} "
        f"transactions={result.transactions} (previous={result.previous_counts})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
