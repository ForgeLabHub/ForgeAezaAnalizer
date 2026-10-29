from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.main import create_app
from backend.app.modules import UnavailableAnalytics


def render() -> str:
    # sort_keys=True: спецификация не зависит от порядка регистрации роутов,
    # поэтому `--check` не даёт ложных расхождений.
    specification = create_app(analytics=UnavailableAnalytics()).openapi()
    return json.dumps(specification, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Экспортировать OpenAPI без запуска БД и модулей")
    parser.add_argument("path", nargs="?", default="backend/openapi.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Не писать файл, а сверить: код возврата 1, если спецификация устарела",
    )
    arguments = parser.parse_args()
    rendered = render()
    target = Path(arguments.path)
    if arguments.check:
        if not target.exists():
            print(f"{target}: файла нет; запустите `make openapi`", sys.stderr)
            return 1
        # Сравниваем разобранный JSON, а не текст: порядок ключей зависит от
        # версии pydantic/fastapi и контрактом не является. Так проверка ловит
        # реальные расхождения (роут, схема, поле), но не шумит из-за
        # переупорядочивания и не вынуждает перезаписывать файл целиком.
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
            expected = json.loads(rendered)
        except json.JSONDecodeError as error:
            print(
                f"{target}: файл не разбирается как JSON ({error}); запустите `make openapi`",
                file=sys.stderr,
            )
            return 1
        if current != expected:
            print(
                f"{target}: расходится с приложением; запустите `make openapi` и закоммитьте",
                file=sys.stderr,
            )
            return 1
        print(f"{target}: совпадает с приложением")
        return 0
    target.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
