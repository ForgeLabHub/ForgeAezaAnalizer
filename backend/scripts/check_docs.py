"""Check that the documentation still matches the code.

Run from the repository root:

    python backend/scripts/check_docs.py

It verifies four things that drift silently:

1. every relative ``*.md`` link in tracked Markdown resolves;
2. every ``AEZA_*`` variable in current docs exists in ``.env.example``;
3. every ``/api/v1/...`` route named in the docs exists in the OpenAPI schema;
4. no documentation example embeds something that looks like a real secret.

It is a consistency gate, not a proof: a route listed in the docs may still be
behaviourally wrong. Exit code 1 means at least one check failed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_PARTS = {"node_modules", ".venv", ".git", "dist", "postgres"}
#: Documentation that intentionally discusses variables it does not own.
ENV_EXEMPT = {"AUTH_ISSUER", "AUTH_FRONTEND_LOGIN_URL", "AUTH_COOKIE_SECURE",
              "OIDC_CLIENT_ID", "OIDC_REDIRECT_URIS", "OIDC_CLIENT_SECRET"}

SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)password\s*=\s*[\"']([^\"'${}]{6,})[\"']"),
)

#: Values that are documentation placeholders or the public demo credential,
#: not secrets. Keep this list short and justified.
SECRET_ALLOWLIST = {"change-me", "example", "your-", "xxx", "<", "placeholder", "demo123"}

#: Routes the framework serves but that do not appear in ``paths``.
FRAMEWORK_ROUTES = {"/api/v1/docs", "/api/v1/openapi.json", "/api/v1/redoc"}


def markdown_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if not SKIP_PARTS & set(p.parts)]


def check_links() -> list[str]:
    problems = []
    for md in markdown_files():
        text = md.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"\]\(([^)#:]+?\.md)(?:#[^)]*)?\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://")):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                problems.append(f"{md.relative_to(ROOT)} -> {target}")
    return problems


def check_env_vars() -> list[str]:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", example, re.MULTILINE))
    declared |= {"AEZA_ANALYTICS_FACTORY", "AEZA_DATA_DIR", "AEZA_VENV_DIR",
                 "AEZA_HOST", "AEZA_PORT", "AEZA_SOURCE_ZIP"}
    problems = []
    for md in markdown_files():
        # Dated audits record historical settings and are not live guidance.
        if "audits" in md.relative_to(ROOT).parts:
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        for name in set(re.findall(r"\b(AEZA_[A-Z0-9_]+)\b", text)):
            if name in declared or name in ENV_EXEMPT:
                continue
            problems.append(f"{md.relative_to(ROOT)}: {name} not in .env.example")
    return sorted(set(problems))


def check_routes() -> list[str]:
    spec_path = ROOT / "backend" / "openapi.json"
    if not spec_path.exists():
        return ["backend/openapi.json missing; cannot verify documented routes"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    paths = set(spec.get("paths", {}))
    # Every documented prefix of a real route, so "/api/v1/customers/10" matches
    # "/api/v1/customers/{customer_id}" and "/api/v1/auth" matches "/api/v1/auth/login".
    prefixes: set[str] = set()
    for path in paths:
        segments = path.split("/")
        for i in range(2, len(segments)):
            prefixes.add("/".join(segments[:i]))
    problems = []
    for md in markdown_files():
        text = md.read_text(encoding="utf-8", errors="replace")
        for route in set(re.findall(r"/api/v1/[A-Za-z0-9_{}/.]+", text)):
            route = route.rstrip(".")
            if route in FRAMEWORK_ROUTES or route in paths:
                continue
            if route.startswith("/api/v1/export/"):
                route = route.rsplit(".", 1)[0]
                if route in paths:
                    continue
            if any(route == p or route.startswith(p + "/") for p in prefixes):
                continue
            problems.append(f"{md.relative_to(ROOT)}: {route} not in openapi.json")
    return sorted(set(problems))


def check_secrets() -> list[str]:
    problems = []
    for md in markdown_files():
        text = md.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            for hit in pattern.finditer(text):
                value = hit.group(0)
                lowered = value.lower()
                if any(word in lowered for word in SECRET_ALLOWLIST):
                    continue
                problems.append(f"{md.relative_to(ROOT)}: possible secret {value[:24]}")
    return problems


def main() -> int:
    groups = {
        "broken relative links": check_links(),
        "unknown AEZA_* variables": check_env_vars(),
        "routes absent from openapi.json": check_routes(),
        "possible secrets in docs": check_secrets(),
    }
    failed = False
    for label, problems in groups.items():
        if problems:
            failed = True
            print(f"FAIL  {label}: {len(problems)}")
            for item in problems:
                print(f"        {item}")
        else:
            print(f"ok    {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
