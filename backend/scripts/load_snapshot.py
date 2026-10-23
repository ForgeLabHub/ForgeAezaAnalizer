from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import Core, NotReadyError
from backend.app.config import get_settings
from backend.app.db import Database
from backend.app.modules import CalculationAdapter, load_module
from backend.app.storage import Storage


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Атомарно загрузить снимок и опубликовать расчёт")
    parser.add_argument("path", nargs="?", default=settings.snapshot_path)
    arguments = parser.parse_args()
    database = Database(settings.database_url)
    try:
        payload = json.loads(Path(arguments.path).read_text(encoding="utf-8"))
        database.initialize()
        calculation = CalculationAdapter(load_module(os.getenv("AEZA_ANALYTICS_FACTORY", "")))
        state = Core(Storage(database), calculation, settings.reference_now).update(source=payload, actor="cli")
        print(json.dumps(state.metadata(), ensure_ascii=False))
        return 0
    except (OSError, ValueError, NotReadyError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
