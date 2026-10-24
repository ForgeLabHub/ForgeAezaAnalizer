# LLM integration audit

Date: 2026-10-24. Branch `feat/deployment-readiness` (merged into local `main`).
Product: Aéza Sentinel, `backend/app/` + `frontend/`.

## 1. What was implemented

A local-LLM assistant, wired into the existing customer card. It **narrates** the
deterministic calculation; it never produces a number of its own.

| Layer | File | Responsibility |
| --- | --- | --- |
| Fact extraction | `backend/app/domain/llm.py` → `build_customer_context` | copies a fixed whitelist out of one customer's payload |
| Prompting | `llm.render_messages` | one system prompt with hard rules + the fact block |
| Provider client | `llm.OllamaClient` | talks to Ollama's `/api/chat`; `probe()` checks `/api/tags` |
| Grounding control | `llm.verify_grounding` | rejects any number or e-mail not present in the facts |
| Orchestration | `llm.explain_customer` | ties the above together; raises typed errors |
| HTTP | `backend/app/api/routes_ai.py` | `GET /ai/status`, `POST /ai/customers/{id}/explain` |
| UI | `frontend/src/components/AiPanel.tsx` | availability check, question box, answer, errors |

### Design rules enforced in code

1. **The model never computes.** Scores, exposures and factors come from
   `backend/app/domain/`; the LLM only rephrases them.
2. **A closed fact set.** `build_customer_context` sends the customer's id,
   e-mail, score, category, service counts, euro balances, per-service factors
   and the existing recommendations. It deliberately drops `withdrawBalance`,
   raw cent values and every other customer.
3. **Fabrications are rejected, not published.** `verify_grounding` extracts every
   number and e-mail from the answer and matches it against the facts. A number
   that is not there makes the request fail with **502** and the UI shows nothing.
4. **Read-only.** No endpoint writes data, changes settings or recalculates. A
   test asserts the published generation is unchanged after an explain call.
5. **Honest unavailability.** Disabled provider → **503**; unreachable/timeout →
   **503**; malformed answer → **502**; ungrounded answer → **502**.

### Endpoints

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/api/v1/ai/status` | `{enabled, reachable, model, provider, detail}`; never throws when the provider is down |
| `POST` | `/api/v1/ai/customers/{id}/explain` | body `{question?}` (≤600 chars); 200 grounded / 502 bad or ungrounded / 503 unavailable / 404 unknown customer / 401 unauthenticated |

## 2. Provider and model

- **Provider:** Ollama HTTP API (`/api/chat`, `/api/tags`). No SDK, no new
  dependency — `httpx` was already present for the test client.
- **Model:** `qwen2.5:7b` by default, configurable. The owner started this model
  on their server; the app addresses it by URL only.
- **No secret is involved:** Ollama on localhost needs no key. Nothing is
  hardcoded, so no credential can leak into the frontend, logs or Git.

## 3. Configuration

All of it is environment-driven (`backend/app/config.py`, `.env.example`,
`docker-compose.yml`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `AEZA_LLM_ENABLED` | `0` | Master switch. Off ⇒ notice, no button |
| `AEZA_LLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama address; Compose default `http://host.docker.internal:11434` |
| `AEZA_LLM_MODEL` | `qwen2.5:7b` | Model name |
| `AEZA_LLM_TIMEOUT_SECONDS` | `60` | Request timeout (1–600) |
| `AEZA_LLM_MAX_TOKENS` | `700` | Answer length cap (16–8192) |
| `AEZA_LLM_TEMPERATURE` | `0.2` | Generation temperature (0–2) |

Validation runs at startup when the feature is on: the URL must be http(s), the
model non-empty, the numbers in range. A bad value fails fast instead of at the
first request.

**Compose note:** the container reaches a host-run Ollama through
`host.docker.internal`, which required adding
`extra_hosts: ["host.docker.internal:host-gateway"]` for Linux.

## 4. Tests actually run

`backend/tests/test_llm.py` — **25 tests, all passing.** The provider is never
really contacted; an `httpx.MockTransport` stands in for Ollama, so every branch
is deterministic.

| Area | Tests |
| --- | --- |
| Grounding verifier | accepts context numbers, accepts a rounded number, rejects an invented number, rejects an invented e-mail, allows small ordinals |
| Fact set | excludes `withdrawBalance` and raw cents; keeps explanatory euro strings |
| Client | good response, timeout, connection error, malformed JSON, empty content |
| Orchestration | ungrounded answer rejected, disabled feature refused |
| HTTP | status enabled/reachable, status unreachable, explain 200 grounded, 503 provider down, 503 timeout, 502 ungrounded, 502 malformed, 401 unauthenticated, 404 unknown customer, 422 oversized question, generation unchanged, disabled ⇒ 503 |

Commands and results:

| Command | Result |
| --- | --- |
| `cd backend && python -m pytest tests/test_llm.py -q` | **25 passed** |
| `cd backend && python -m pytest tests/ -q` | **239 passed** (214 before + 25) |
| `python -m pytest tests/ -q` (root) | **69 passed** |
| `cd frontend && npx tsc -b` | exit 0 |
| `cd frontend && npm run build` | exit 0 |
| `python backend/scripts/check_docs.py` | 4/4 ok |
| `docker compose config` | valid |

### Verification with a real HTTP server, not only mocks

A throwaway stdlib HTTP server that mimics Ollama was started on
`127.0.0.1:11434`, and the app was run with `AEZA_LLM_ENABLED=1`. Results over
real HTTP:

| Scenario | Result |
| --- | --- |
| `GET /ai/status` with the stub up | `enabled: true, reachable: true, model: qwen2.5:7b` |
| `POST /explain` with the stub answering | **200**, `grounded: true`, text contained the real score 71.4 |
| stub killed, `POST /explain` | **503** `"Локальная модель недоступна"` |
| stub replaced by one that answers "вероятность 99 %, 12345 евро" | **502** `"…содержит данные, которых нет в расчёте (число 99…; число 12345…)"` |
| `AEZA_LLM_ENABLED=0` | `enabled: false`; explain → **503** |
| Browser walkthrough | answer rendered in the card; with the feature off the card shows a notice and **no button**; all other features kept working |

## 5. Limitations (still true)

1. **The real `qwen2.5:7b` was not exercised from this environment.** Ollama is
   not installed here: no binary, no process, nothing on port 11434. The owner
   ran it on their server. Everything above was verified against a faithful stub,
   which proves the integration path but **not** the model's own answer quality.
2. **The grounding check is numeric and e-mail based.** It catches invented
   figures and addresses; it cannot detect a *qualitative* fabrication ("the
   customer wrote that they are leaving") that contains no number. The system
   prompt forbids it and the fact block is the only data channel, but this is a
   prompt-level control, not a proof.
3. **`/explain` is synchronous.** A slow model blocks that one request for up to
   `AEZA_LLM_TIMEOUT_SECONDS`. Acceptable for one analyst; would need a queue or
   streaming for many.
4. **No answer cache.** Repeated clicks re-query the model.
5. **Single-turn.** The `question` field is an extra instruction on the same
   fact set, not a conversation with memory.
6. **The feature is off by default**, so on any deployment that has not set
   `AEZA_LLM_ENABLED=1` the UI shows the notice. That is intended, not a bug.
7. **Not verified on production.** The stand still runs `origin/main` and has no
   `/api/v1/ai/*` routes.

## 6. How to run the demonstration

Local, with a real Ollama:

```bash
# 1. Ollama, on the host:
ollama serve            # listens on 127.0.0.1:11434
ollama pull qwen2.5:7b

# 2. The app, from the repository root:
export AEZA_JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export AEZA_ADMIN_PASSWORD="demo123"
export AEZA_DATABASE_URL="sqlite:///$(pwd)/data/analytics.sqlite"
export AEZA_AUTH_DATABASE_URL="sqlite:///$(pwd)/db/auth.sqlite3"
export AEZA_ANALYTICS_FACTORY="backend.app.domain.module:create"
export AEZA_SEED_DEMO_DATA=1
export AEZA_LLM_ENABLED=1
export AEZA_LLM_BASE_URL="http://127.0.0.1:11434"
export AEZA_LLM_MODEL="qwen2.5:7b"
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# 3. Frontend, second terminal:
cd frontend && npm install && npm run dev
```

Then open `http://127.0.0.1:5173/customers/10`, log in, and use the
**«ИИ-объяснение риска»** card.

Docker Compose variant: `AEZA_LLM_ENABLED=1 docker compose up --build` (the
Compose default already points at `host.docker.internal:11434`).

**Without Ollama**, leave `AEZA_LLM_ENABLED=0`: the card explains that the model
is off and the rest of the product works normally.

## 7. What is needed to enable it in production

1. Confirm Ollama is reachable **from the API container**, not just from the
   host shell: `docker compose exec api python -c "import urllib.request;
   print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags',
   timeout=3).status)"`.
2. Confirm the model name matches: `ollama list`.
3. Set `AEZA_LLM_ENABLED=1`, `AEZA_LLM_BASE_URL`, `AEZA_LLM_MODEL` for the `api`
   service and redeploy.
4. Expect a first-request latency while the model loads into memory.
5. Nothing else: no secret, no firewall change beyond the host port already used
   by Ollama.

**Not done, and deliberately:** no push, no deploy, no change to production.

## 8. Residual risk summary

| Risk | Mitigation in place | Remaining |
| --- | --- | --- |
| Invented figures | numeric + e-mail grounding check, 502 on violation | qualitative claims not covered |
| Prompt injection via data | data is passed as a JSON block; system prompt forbids deviation | a hostile *customer name* is not sanitised |
| Model writes data | endpoints are read-only; a test pins the generation | none observed |
| Secret leakage | no secret exists for local Ollama; URL from env only | none |
| Silent failure | every failure path returns 5xx with a reason; UI shows it | none |
| Cost / runaway generation | `AEZA_LLM_MAX_TOKENS` and timeout bound each call | no rate limit per user |
