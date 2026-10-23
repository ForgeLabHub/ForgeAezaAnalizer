"""Command-line entry points: import the dataset, profile it, or serve the API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import settings


def cmd_import(args: argparse.Namespace) -> int:
    from .importer import import_dataset

    source = Path(args.source) if args.source else None
    try:
        result = import_dataset(source, strict=not args.lenient)
    except (FileNotFoundError, ValueError) as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1
    payload = result.as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result.nested_archives:
        print(f"note: nested archives not extracted: {result.nested_archives}", file=sys.stderr)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .audit import profile_store
    from .db import get_session_factory, init_db

    init_db()
    session = get_session_factory()()
    try:
        profile = profile_store(session)
    finally:
        session.close()
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "aeza_analyzer.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aeza", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="import the organiser dataset into the store")
    imp.add_argument("--source", help="ZIP archive or extracted directory (default: датасет.zip)")
    imp.add_argument(
        "--lenient",
        action="store_true",
        help="store valid rows even if some rows are rejected (default: abort)",
    )
    imp.set_defaults(func=cmd_import)

    aud = sub.add_parser("audit", help="print a reproducible profile of the stored data")
    aud.set_defaults(func=cmd_audit)

    srv = sub.add_parser("serve", help="run the web application")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--reload", action="store_true")
    srv.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
