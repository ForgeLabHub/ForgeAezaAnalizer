# AI Analyst — verified technical plan

Status: **plan only.** Nothing in this document is implemented. It records the
integration points that were *read from the code and confirmed by running
commands*, so a future implementer does not have to rediscover them.

Scope constraint for the current task: **no language model is installed and no
infrastructure is changed.** This plan describes how a local AI Analyst would be
attached later, and what already exists to attach it to.

---

## 1. Environment facts (measured 2026-10-24)

| Check | Result |
| --- | --- |
| `ollama`, `llama-cli`, `llama-server`, `vllm` on `PATH` | absent |
| Python `transformers`, `torch`, `llama_cpp`, `onnxruntime`, `sentence_transformers` | absent |
| Python `openai`, `anthropic` SDKs | absent |
| CPU / RAM available | 4 cores, ~11 GiB available |
| Disk on `/workspace` | 25 GiB, 1 % used |

Consequence: the analyst must be **provider-agnostic** and degrade gracefully to
"no analyst configured", exactly as the analytics module does today via
`AEZA_ANALYTICS_FACTORY` (an empty value yields `UnavailableAnalytics`, which
raises `NotReadyError` → HTTP 503). Reuse that pattern rather than inventing a
second one.

## 2. What the analyst is allowed to see

The analyst is a **read-only narrator over numbers the engine already computed.**
It must never do arithmetic on raw money fields or invent a score. The reasons are
structural, not stylistic:

- Money is integer eurocents internally (`backend/app/domain/money.py`); euros are
  a display concern added at the API boundary (`*_eur` strings). A model summing
  `balance` + `totalReplenished` would produce a number the product explicitly
  says is meaningless (`README.md`: balance and top-ups are not revenue).
- `revenue_at_risk` depends on `risk_score` and on whether a renewal falls inside
  the horizon. Re-deriving it in prose risks double-counting renewals, which
  `docs/REVENUE_METHODOLOGY.md` forbids.

Therefore the analyst reads from the same computed artefacts the UI reads:

| Source | Route / symbol | Confirmed |
| --- | --- | --- |
| Fleet summary | `GET /api/v1/analytics/summary` | 200, 10 customers, high 3, exposure 5.80 € |
| Customer list | `GET /api/v1/customers` (paged, sorted) | 200 |
| Customer detail | `GET /api/v1/customers/{id}` | 200 for id 10, 404 for unknown |
| Published model | `GET /api/v1/model/settings` | 200, weights sum 13.0, `isDefault: true` |
| Action list | `GET /api/v1/priority` | 200, total 10, category counts 3/3/2/7 |
| Scenario compare | `POST /api/v1/scenarios/compare` | 200, publishes nothing |
| Data-quality issues | `inspect_source()` in `backend/app/domain/insights.py` | pure function |

These are exactly the routes already exercised by the live scenario tests and
documented in `docs/API.md` (21 operations across 19 paths).

## 3. Proposed shape

```
frontend  ──POST /api/v1/analyst/ask──►  API route (auth: analyst session)
                                              │
                                              ├─► tool layer (pure, no LLM)
                                              │     reads summary/customer/priority
                                              │
                                              └─► provider adapter (pluggable)
                                                    ├─ LocalRuntimeProvider (Ollama / llama.cpp)
                                                    └─ UnavailableProvider  (default)
```

### 3.1 Provider adapter — mirrors `AnalyticsModule`

Reuse the existing contract style in `backend/app/modules.py`:

```python
class AnalystProvider(Protocol):
    def answer(self, question: str, tools: ToolRegistry) -> AnalystAnswer: ...
    def health(self) -> dict: ...
```

Selection via a new env var, defaulting to off:

```
AEZA_ANALYST_FACTORY=backend.app.analyst.local:create   # or empty = disabled
AEZA_ANALYST_MODEL=...                                   # provider-specific
```

An empty `AEZA_ANALYST_FACTORY` must yield `UnavailableAnalyst`, whose
`answer()` raises `NotReadyError`, which the existing exception handler already
maps to 503 with a Russian message. **No new error path is required** — this was
verified by reading `backend/app/main.py` and the 503 behaviour that
`docs/API.md` documents for an unconfigured analytics module.

### 3.2 Tool layer (deterministic, unit-testable, no LLM)

Each tool is a thin function over an existing call, so it can be tested without a
model:

| Tool | Wraps | Guard |
| --- | --- | --- |
| `get_summary()` | `runtime.storage.summary()` | returns stored payload, no recompute |
| `get_customer(id)` | `GET /customers/{id}` serializer | 404 → tool returns "not found" |
| `list_high_risk()` | `GET /customers?riskCategory=high` | confirmed param name in `routes_customers.py` |
| `explain_customer(id)` | detail payload's `reasons`/`missingData` | verbatim, not paraphrased |
| `get_priority()` | `GET /priority` | |
| `compare_scenario(overrides)` | `insights.compare()` | never publishes |
| `get_quality_issues()` | `inspect_source()` | |

Grounding rule to enforce in code: **every number in an answer must carry the
tool call that produced it.** A response that cites a figure with no tool result
is a defect and should be rejected by a post-check, not just discouraged by the
prompt. This is the same standard the UI already meets ("no invented metrics").

### 3.3 Refusal surface

The analyst must reproduce, not contradict, the product's stated limits:

- The score is **not** a churn probability (`docs/model.md`); the analyst may not
  say "вероятность оттока 71 %".
- `deleted` / `blocked` services are concluded events, not forecasts.
- Balance and `totalReplenished` are not revenue at risk.

Encoding these as fixed refusal strings (returned without a model call) is
cheaper and safer than relying on prompt adherence.

## 4. API addition (future)

```
POST /api/v1/analyst/ask     { "question": "..." }  → { "answer", "citations", "tools" }
GET  /api/v1/analyst/health                          → { "enabled", "model", "ready" }
```

- Auth: existing analyst session (`UserDep`), same as every other `/api/v1` route.
- `citations`: the tool calls and their identifiers, so the UI can deep-link to
  the customer card.
- No PII in logs or metrics: customer emails and ids must not become Prometheus
  labels, consistent with the existing `aeza_*` metric set (aggregate only).

## 5. Frontend (future)

A side panel on the dashboard and customer card. It renders `citations` as links,
so a claim is one click from the evidence. When `AEZA_ANALYST_FACTORY` is empty,
the panel shows a disabled state with the same "не подключён" wording the
analytics 503 already uses — no fake chat.

## 6. Why this is not built now

The current task explicitly forbids installing models or changing infrastructure,
and the demo runs entirely on the explainable rule-based engine. The plan above is
written so that enabling the analyst later is an additive change: one new router,
one provider package, one frontend panel — with the tool layer, error path,
metrics conventions and refusal rules all reusing mechanisms that already exist
and are already covered by tests.

## 7. Open questions for the implementer

1. Which local runtime — Ollama (simplest install) or a bundled `llama.cpp`
   server (no daemon)? Both fit the adapter; neither is installed today.
2. Is an analyst answer allowed to trigger a scenario *comparison* (read-only) but
   never a publish? This plan assumes yes for compare, no for publish.
3. Retention: should asked questions be stored for audit? If yes, they need a
   table and a PII policy; the product currently stores no free-text user input.
