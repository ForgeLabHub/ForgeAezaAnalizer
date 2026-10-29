# Module specification: template

English version of [../../modules/module-template.md](../../modules/module-template.md).

Copy it to `docs/modules/<name>.md`. All 11 sections are mandatory —
`scripts/docs-check.sh` verifies them in CI.

## 1. Purpose and boundaries
What the module does, what it does not do, where its responsibility ends.

## 2. Use scenarios
User or system → what happens → what is observable, including failures.

## 3. Contract
Routes, schemas, events, error codes; a reference to `backend/openapi.json`.

## 4. Data
Which tables or files the module writes (it is the only writer) and what it reads through
other contracts. Snapshot, aggregates, provenance.

## 5. Access rules
Who has access, what happens on refusal, how it is verified.

## 6. Dependencies
Incoming (who calls it) and outgoing (whom it calls), the port or adapter for an external
system.

## 7. Configuration
`AEZA_*` variables with defaults, whether they are mandatory, and the consequences of a
wrong value.

## 8. Build and debug
How to run just this module, how to reproduce the behaviour locally.

## 9. Tests
Which tests prove what (files, test names).

## 10. Observability
Logs, metrics, error codes, what the operator does on failure.

## 11. Limitations and readiness
Known limitations, what was deliberately left out, readiness criteria.
