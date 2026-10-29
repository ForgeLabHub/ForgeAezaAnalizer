# Module: AI Analyst and assistant

English version of [../../modules/ai-analyst.md](../../modules/ai-analyst.md).

## 1. Purpose and boundaries

Answers questions about the data through tools rather than direct database access:
`backend/app/ai/tools/{analytics,customers,scenarios,actions}.py`. The model provider is
replaceable (`ai/providers/base.py`, implementations `ollama.py`, `mock.py`).
It does not execute arbitrary SQL, does not reach data bypassing the tools, and does not
work when `AEZA_AI_ENABLED=0`.

## 2. Use scenarios

- The question "which services are at risk" → a tool call → an answer with numbers and
  sources.
- An answer without a model (mock provider) in tests and with AI disabled.
- Failure: the provider is unavailable → a clear error, regular calculations keep working.

## 3. Contract

`/api/v1/ai/*`, `/api/v1/model/*` in `backend/openapi.json`. The internal contract is
`ai/service.py` and the schemas in `ai/schemas.py`; tools declare their input and output
explicitly.

## 4. Data

No tables of its own: reading goes through tools that call the analytics domain. Answers are
not stored as a source of truth — numbers always come from the domain.

## 5. Access rules

Authentication is required; the tools are available only within the analyst role. Input and
output safety checks live in `ai/safety.py` (escaping, context limits).

## 6. Dependencies

Outgoing: the analytics domain, the LLM provider over HTTP, the RAG index
(`ai/rag/index.py`). Incoming: `backend/app/api/routes_ai.py`.

## 7. Configuration

`AEZA_AI_ENABLED`, `AEZA_AI_PROVIDER`, `AEZA_AI_MODEL`, `AEZA_AI_BASE_URL`,
`AEZA_AI_MAX_TOKENS`, `AEZA_AI_TIMEOUT_SECONDS`, `AEZA_LLM_*`, `AEZA_OLLAMA_*`.
Disabled by default: AI is an option, not a condition of the product working.

## 8. Build and debug

```bash
python -m pytest backend/tests/test_ai.py -q
python -m backend.app.ai.rag --docs ./docs --out backend/data/rag_index.json
```

## 9. Tests

`backend/tests/test_ai.py`: tool calls, the disabled mode, the mock provider, protection
against unsafe output. The "AI is not a source of truth" check — numbers in the answers
match the domain.

## 10. Observability

The provider state is visible through `/api/v1/model/*`; provider errors are logged without
prompt contents. Latency metrics — `/metrics`; the default timeout of 420 s shows up for the
operator as long requests.

## 11. Limitations and readiness

- Answer quality is not guaranteed; it is compensated by taking the numbers from the domain.
- The RAG index is built into the image at build time — after changing `docs/` a rebuild is
  required.
- Readiness: with AI disabled the product is fully functional; the tools cannot expose data
  the user is not allowed to see.
