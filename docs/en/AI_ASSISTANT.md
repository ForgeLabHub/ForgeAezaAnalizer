# AI assistant

English version of [../AI_ASSISTANT.md](../AI_ASSISTANT.md).

The endpoint `POST /api/v1/insights/ai` phrases an answer over the aggregates of the
published analytics. The local Ollama is disabled by default; without it the rest of the
application works.

To enable the assistant, install Ollama, pull the required model and set in `.env`:

```dotenv
AEZA_LLM_ENABLED=1
AEZA_OLLAMA_URL=http://host.docker.internal:11434
AEZA_OLLAMA_MODEL=qwen2.5:7b
```

The address must be reachable from the API container. After changing `.env` run
`docker compose up -d api`.

The request requires a Bearer token. The model receives aggregated data, not individual
customer records. It explains the published metrics rather than recomputing them. The
request schema and parameters are at `/api/v1/docs`; the full settings list is in
`.env.example`.
