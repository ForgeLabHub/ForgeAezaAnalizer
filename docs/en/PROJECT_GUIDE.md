# Project guide

English version of [../PROJECT_GUIDE.md](../PROJECT_GUIDE.md).

## Layout

- `frontend/` — the React and TypeScript interface.
- `backend/app/` — FastAPI, the API, data import and the calculations.
- `backend/auth/` — accounts and sessions.
- `dataset/data.json` — the initial synthetic snapshot.

Docker Compose runs the interface, the API and PostgreSQL. Accounts and sessions are
stored separately in SQLite.

## Data

The snapshot contains the arrays `accounts`, `services` and `transactions`. On the first
start with an empty database it is validated and imported. A new snapshot is uploaded as a
whole through `PUT /api/v1/source/snapshot`; on failure the previously published data is
kept.

The data is synthetic and contains no labelled churn history.

## Risk and revenue

The risk of a service is a weighted estimate over the available factors in the 0–100
range. Missing factors are excluded from the calculation. The risk of a customer is the
maximum score among its forecast services.

Forecast services are those with the statuses `active`, `suspended` and `prolong_wait`.
The statuses `deleted` and `blocked` already describe a finished state and are not
forecast. The score is not a churn probability.

Revenue at risk does not affect the score: the price of each paid renewal inside the chosen
horizon is multiplied by the risk of the service and counted once. Monetary fields are
stored in euro cents; `transactions.amount` is not used as a sum of money.

## API

The current request and response schemas are available at `/api/v1/docs`. Private routes
require a Bearer token after signing in through `/api/v1/auth/login`. Service state:
`/health` and `/ready`.
