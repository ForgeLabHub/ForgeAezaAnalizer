# Code style and lint

English version of [../../development/code-style.md](../../development/code-style.md).

## What is checked and with what

| Tool | Version | Configuration | Where it runs |
| --- | --- | --- | --- |
| ruff | `>=0.17,<0.18` (`requirements-dev.txt`) | `ruff.toml` | `make lint`, `make verify`, CI |
| pytest | `>=8` | `pytest.ini`/`pyproject.toml` | `make test-backend`, `make test-auth` |
| openapi | — | `backend/openapi.json` | `make openapi-check` |

The linter configuration lives in the repository (`ruff.toml`) rather than in the defaults:
the result must not depend on the ruff version installed on a developer machine.

## Why the rule set is narrow

`select = ["E9", "F"]` — syntax, undefined names, unused imports and variables. That is what
almost always points at a real bug. The strict sets (`I`, `UP`, `BLE`, `ISC`, `SIM`, `PLW`)
produce hundreds of style findings in this code; enabling them is a separate task with its
own review, not a side effect of a migration.

Tightening order:

1. Take one set (for example `I` — import sorting).
2. `ruff check --select I --fix`, a separate pull request, run the tests.
3. `# noqa: <code>` with a comment where the behaviour is intentional.
4. Add the set to `select` only after CI is green.

## Commands

```bash
make lint        # ruff over the whole repository
make test-backend
make test-auth
make verify      # lint + docs-check + tests + openapi-check
```

## Agreements

- New code comes with a test; a test does not need the network or PostgreSQL when it checks
  the domain.
- Money goes through `domain/money.py` only; `float` is forbidden in calculations.
- Every number in an API response has provenance (`domain/provenance.py`).
