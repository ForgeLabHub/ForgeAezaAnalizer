# AI Analyst

English version of [../AI_ANALYST.md](../AI_ANALYST.md).

AI Analyst is an optional feature that explains the analytics with a local Ollama model. It
is disabled by default and takes no part in the risk calculation.

## Enabling

Install Ollama, pull a model and point `.env` at an address reachable from the API
container:

```bash
ollama pull qwen2.5:3b-instruct
```

```dotenv
AEZA_AI_ENABLED=1
AEZA_AI_PROVIDER=ollama
AEZA_AI_MODEL=qwen2.5:3b-instruct
AEZA_AI_BASE_URL=http://host.docker.internal:11434
```

The value `host.docker.internal` suits the project's Compose configuration. After changing
`.env` recreate the API: `docker compose up -d api`.

## Usage

The API reference is at `/api/v1/docs`. The main routes: `GET /api/v1/ai/status`,
`POST /api/v1/ai/chat` and `POST /api/v1/ai/customers/{id}/explain`. The routes require
authentication.

The model phrases an explanation based on the application data and does not change the
snapshot or the settings. The risk score remains a heuristic, not a churn probability. Other
Ollama parameters are listed in `.env.example`.
