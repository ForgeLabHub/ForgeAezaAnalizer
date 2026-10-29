# System context

English version of [../../architecture/system-context.md](../../architecture/system-context.md).

## What this is

A web application for assessing service-renewal risk and the revenue at risk. The risk
score is an **explainable weighted heuristic**, not a churn probability: the dataset has no
labelled outcomes. That is a product limitation, not an implementation defect.

## Context diagram

```
        +------------+   +--------------+   +---------------+
        | Analyst    |   | Telegram     |   | External      |
        | (browser)  |   | Mini App/bot |   | source        |
        +-----+------+   +------+-------+   | (snapshot)    |
              | HTTPS           |           +-------+-------+
              v                 v                   | PUT /api/v1/source/snapshot
        +------------------------------------+      |
        | web (nginx + React build)          |      |
        +-----+------------------------------+      |
              | /api/v1/*                          |
              v                                    v
        +-----------------------------------------------------+
        | api (FastAPI)                                       |
        |  backend/app: analytics domain, API, AI, metrics    |
        |  backend/auth: accounts, JWT, sessions              |
        +------+-----------------------+----------------------+
               |                       |
               v                       v
        +--------------+        +-------------------+
        | PostgreSQL16 |        | SQLite (auth db)  |
        | analytics    |        | users, sessions,  |
        |              |        | keys              |
        +--------------+        +-------------------+
               |
               v optionally
        +--------------------------------------------+
        | Ollama/LLM · SMTP · Telegram Bot API       |
        +--------------------------------------------+
```

## Two databases — a deliberate decision

- **PostgreSQL** — domain data (accounts, services, transactions, aggregates).
- **SQLite** — authentication only (`AUTH_DATABASE`).

The point: the authentication module can be used and tested on its own without
PostgreSQL (`tests/test_auth.py` runs without the analytics database). The price: two
backup mechanisms, both described in [operations/deployment.md](../operations/deployment.md).

## Supported scope

Declared: PostgreSQL 16, Python 3.12, Linux + Docker Compose, Chromium-compatible
browsers. Not declared: other DBMS, running the analytics part without PostgreSQL, scaling
to several `api` replicas without external state (the snapshot and the cache live in the
process).

## Failure modes of external systems

| Dependency | Mandatory | When missing |
| --- | --- | --- |
| PostgreSQL | yes | the application serves no analytics |
| LLM (Ollama and others) | no | AI features are off, calculations work |
| SMTP | no | e-mail is not sent |
| Telegram | no | the integration is off |
