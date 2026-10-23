from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.main import create_app
from backend.app.modules import UnavailableAnalytics


def main():
    parser = argparse.ArgumentParser(description="Экспортировать OpenAPI без запуска БД и модулей")
    parser.add_argument("path", nargs="?", default="backend/openapi.json")
    arguments = parser.parse_args()
    specification = create_app(analytics=UnavailableAnalytics()).openapi()
    Path(arguments.path).write_text(json.dumps(specification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
