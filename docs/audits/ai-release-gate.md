# AI release gate — actual state

Verified: **2026-10-24**, by running commands against this working copy. Nothing in
this document is carried over from an earlier report; every line was re-measured.

> ## UPDATE (later the same day) — the headline below is now superseded
>
> The finding below was correct **for this working copy and for `origin/main` at
> `bcadc2f`**. While re-checking, `origin/main` was found to have advanced to
> **`17addd9`**, which *does* contain a complete AI Analyst:
>
> ```
> 17addd9 merge: integrate origin/main (bcadc2f) into AI Analyst + retention actions
> aa0d588 docs(ai): warn against storing model weights inside the repo tree
> 7ca9d37 feat(ai): local grounded AI Analyst + human-confirmed retention actions
> ```
>
> That work is a **superset** of what the brief described and supersedes the
> `llm.py` / `routes_ai.py` / `AiPanel.tsx` file names in the brief:
>
> | Brief's name | Actual file on `origin/main` |
> | --- | --- |
> | `backend/app/domain/llm.py` | `backend/app/ai/{service,context_builder,safety,schemas,config}.py` |
> | `backend/app/api/routes_ai.py` | `backend/app/api/routes_ai.py` (present) |
> | `frontend/src/components/AiPanel.tsx` | `frontend/src/components/AIAnalystPanel.tsx` |
> | — | `backend/app/ai/providers/{base,mock,ollama}.py`, `backend/app/ai/rag/`, `backend/app/ai/tools/` |
> | — | `backend/tests/test_ai.py`, `backend/tests/test_actions.py` |
>
> It adds a RAG index over `docs/`, tool-calling over the analytics/customers/
> scenarios services, a grounding-validation safety layer, a mock provider for
> offline tests, and an Ollama provider that **refuses non-private hosts** unless
> `AEZA_AI_ALLOW_REMOTE=1`. It is configured by `AEZA_AI_*` (not `AEZA_OLLAMA_*`)
> and is **off by default** (`AEZA_AI_ENABLED=0`).
>
> Consequences for this document: §0 and §2 describe the state of *this checkout*
> and are retained for the record, but they no longer describe the repository as a
> whole. §5's "no AI settings to leak" and §7's `host.docker.internal` blocker are
> also superseded — the upstream integration handles host resolution and its own
> configuration. **The correct action is to merge `origin/main`, not to rebuild the
> feature**, which is what §10's blocker #1 anticipated.

## 0. Headline finding (as measured against this checkout, `origin/main` at `bcadc2f`)

**The AI Analyst integration described in the task brief does not exist in this
working copy, in any local commit, or on any local branch.**

The brief stated that the branch is `main`, HEAD is `fa991e1`, the tree is clean,
and the integration lives in `backend/app/domain/llm.py`,
`backend/app/api/routes_ai.py` and `frontend/src/components/AiPanel.tsx`, verified
against an Ollama HTTP stub with `qwen2.5:7b`.

None of that matches the actual repository. Stages B–F of the brief (audit the
local-AI code, smoke-test the real model, Docker smoke test, UX check) are
therefore **not executable as written** — there is no code to audit and no
endpoint to smoke-test. What follows records the evidence, then audits the
foundation the integration was meant to reuse, which does exist and is verifiable.

## 1. Git state

| Claim in brief | Measured |
| --- | --- |
| Branch `main` | `main` — **matches** |
| HEAD `fa991e1` | **`fe554bc`** — no match |
| Commits `fa991e1`, `02fbbc9`, `af51a24` | **all three absent** (`git cat-file -t` → not found) |
| Working tree clean | **35 entries dirty** (28 modified, 7 untracked) |

```
$ git rev-parse --show-toplevel   → /workspace/project
$ git rev-parse --abbrev-ref HEAD → main
$ git rev-parse HEAD              → fe554bc4509430a934dc28911abbe0a3df67a379
$ git log -5 --oneline
  fe554bc Record the push-access blocker and the seed/README data divergence in AGENTS.md
  3a8f8fc Add provenance audit and a deploy guide for the canonical product
  aead0cc Merge origin/main, keeping both sides' work
  10a7454 Refresh defence decks and docs to match the verified product state
  d6a027c (tag: pre-merge-backup) Correct documentation to match the current model defaults
```

`origin/main` had advanced to `bcadc2f`; I fetched read-only and confirmed the AI
files are absent there too.

## 2. Evidence that the AI work is absent

Checked every plausible location. All negative:

| Search | Result |
| --- | --- |
| `backend/app/domain/llm.py`, `backend/app/api/routes_ai.py`, `frontend/src/components/AiPanel.tsx` | absent |
| `docs/AI_DEMO.md`, `docs/audits/llm-integration-audit.md`, `docs/audits/ai-release-gate.md` | absent (directory `docs/audits/` did not exist) |
| `backend/scripts/check_docs.py` | absent; `backend/scripts/` holds only `export_openapi.py`, `export_seed.py`, `load_snapshot.py` |
| `git rev-list --all --objects \| grep -iE "routes_ai\|domain/llm\|AiPanel\|AI_DEMO\|release-gate\|check_docs"` | **no hits** — never committed, in any commit |
| `git ls-tree -r origin/main` for the same names | no hits |
| GitHub API: branches, open+closed PRs, all repos under `Pixelminds-hub` | one repo, five branches (`main`, `feat/analytics-scenarios`, `feat/churn-risk-analyzer`, `feat/data-integration-analytics`, `feat/priority-whatif-integration`), **zero PRs**, no AI branch |
| `find / -xdev` for the file names | no hits |
| second checkout `/tmp/aeza-clean` | AI files absent |
| handoff bundle + tarball (`/workspace/handoff/`) | `tar tzf … \| grep -iE "llm\.py\|routes_ai\|AiPanel"` → no hits; `grep -c ollama\|qwen2.5` → **0** |
| `/workspace/bash_events` for `ollama`/`routes_ai`/`qwen2.5` | no hits — no such command was ever run in this environment |
| `frontend/dist/assets/*.js` for `ollama`/`qwen`/`ai/status` | 0 matches |
| Live API `GET /api/v1/openapi.json` | 19 paths, **no** AI/analyst path |

The only `ollama` artifact on the machine is `/tmp/_MEI…/ollama-0.6.0.dist-info` —
the **Python client library** ("The official Python client for Ollama"), extracted
by a PyInstaller bundle. It is not importable from the project interpreter and is
not a server. It is not part of this repository.

## 3. What the brief asked for, mapped to reality

| Stage | Feasible? | Why |
| --- | --- | --- |
| A — confirm state | **done** | Divergence recorded above |
| B — audit AI security | **not executable** | No `llm.py` / `routes_ai.py` to audit |
| C — prepare real Ollama check | **done (environment measurement)** | Resources measured; Ollama absent; no download attempted |
| D — real end-to-end smoke test | **not executable** | No `/ai/status` or explanation endpoint exists |
| E — AI UX & demo scenario | **not executable** | No `AiPanel.tsx`; no AI surface in the UI |
| F — Docker & Ollama reachability | **done (partly)** | Compose validated and built; `host.docker.internal` finding below |
| G — regressions & docs | **done** | Numbers below; no regressions |
| H — release gate | **done (this file)** | Records the true state |

## 4. Environment (measured 2026-10-24)

| Check | Result |
| --- | --- |
| RAM | 15 GiB total, ~11 GiB available |
| Disk `/workspace` | 25 GiB, 1 % used (~25 GiB free) |
| Disk `/` | 72 GiB, 37 % used (~46 GiB free) |
| CPU | 4 cores |
| Swap | none |
| GPU | `nvidia-smi` unavailable (no NVIDIA tooling) |
| `ollama` on PATH | **absent**; `~/.ollama` absent; no `*.gguf` / `*.safetensors` anywhere |
| Port 11434 (Ollama default) | nothing listening |
| Ollama reachable from containers | not applicable — no server |

**Resource verdict for `qwen2.5:7b`:** the ~4.7 GB download and roughly 5–6 GB of
resident memory would fit this box (25 GiB free disk, ~11 GiB available RAM, no
swap). That is an assessment only — **nothing was downloaded**, per the constraint.

## 5. Foundation audit — what *does* exist and was verified

The integration was meant to reuse these. All confirmed working:

| Property | Evidence |
| --- | --- |
| Auth enforced on every analytics route | no-token `GET` on `/analytics/summary`, `/customers`, `/customers/10`, `/priority`, `/model/settings`, `/source/snapshot` → **401**; with token → 200 |
| Metrics not public | `GET /metrics` without token → **401** |
| Graceful degradation pattern exists | `backend/app/modules.py:32` `UnavailableAnalytics` raises `NotReadyError`; `backend/app/main.py:127` maps `NotReadyError` → **503**; empty `AEZA_ANALYTICS_FACTORY` selects it |
| No AI settings to leak | `backend/app/config.py` has **no** AI/LLM/Ollama settings; `.env.example` has **no** AI variables |
| No AI in the product UI | `frontend/src/App.tsx` routes: `/`, `/customers`, `/customers/:id`, `/action-center`, `/what-if`, `/settings`, `/login` — no AI page |

This is the correct, already-verified substrate: a future analyst endpoint would
inherit auth from the existing dependency and inherit 503-on-unavailable from the
existing exception handler, without inventing a second error path. That design
guidance lives in `docs/AI_ANALYST_PLAN.md`.

## 6. Tests and build (regressions)

| Suite | Expected in brief | Measured |
| --- | --- | --- |
| `backend` pytest | 239 passed | **210 passed**, 1 warning (28.8 s) |
| root pytest | 69 passed | **69 passed**, 1 warning (15.9 s) |
| `npx tsc -b` | success | **success** |
| `npm run build` | success | **success** — `index-Dn_pk6Dg.js` 227.46 kB (gzip 71.82 kB), `index-BJ7jfnGg.css` 25.38 kB |
| docs check | 4/4 | **not applicable** — `backend/scripts/check_docs.py` does not exist and no docs-validation tooling exists in the repo |
| OpenAPI vs routes | — | committed == regenerated: **identical**, 19 paths / 21 operations |
| `docker compose config` | — | **valid** |

No regressions. The backend count is 210, not the 239 in the brief; there is no
239-test state anywhere in this repo, so that figure does not correspond to any
revision here.

## 7. Docker

| Check | Result |
| --- | --- |
| `docker compose config -q` | valid |
| Images | `project-api:latest` 352 MB, `project-web:latest` 74.1 MB, `postgres:16-alpine` 420 MB |
| Containers | `project-api-1`, `project-db-1`, `project-web-1` all **healthy** |
| Health | `GET /health` → `{"status":"ok"}`; `GET /ready` → 200 |
| Served bundle | `index-Dn_pk6Dg.js` + `index-BJ7jfnGg.css` — matches committed `frontend/dist` |
| Baseline | generation 1, 10 customers, 3 high-risk, exposure 5.80 € |

I did **not** tear the stack down; the running containers belong to the current
work and the brief forbids stopping unrelated containers.

### `host.docker.internal` — a real finding

The brief asked whether `host.docker.internal` resolves on this Linux host. It
does **not**:

```
$ sudo docker exec project-api-1 getent hosts host.docker.internal
  (no result)
$ grep -n extra_hosts docker-compose.yml
  (no extra_hosts mapping)
```

`host.docker.internal` is automatic on Docker Desktop (macOS/Windows) but **not**
on plain Linux Docker Engine. Any future AI container that points at a host-run
Ollama via `http://host.docker.internal:11434` will fail to resolve unless the
service adds `extra_hosts: ["host.docker.internal:host-gateway"]`. This is a
concrete integration blocker to fix *before* wiring a real model, and it is not
documented anywhere in the repo today.

## 8. Status ledger

Kept separate on purpose — these are not one word.

| Status | Item |
| --- | --- |
| **1. Implemented** | The explainable risk product: backend, API, UI, settings, import, What-if, Action Center, metrics |
| **2. Verified by unit tests** | 210 backend + 69 root tests; risk scoring, money conversion, thresholds, import atomicity, provenance |
| **3. Verified with an HTTP stub** | Nothing — no AI code exists to stub |
| **4. Verified with a real model** | Nothing — no model installed, no AI code |
| **5. Verified in Docker** | The product stack (healthy, health endpoints, bundle match, `/metrics` auth). **Not** any AI path |
| **6. Verified in production** | Nothing |
| **7. Not verified** | The entire AI Analyst integration — it does not exist. Also unverified: docs-validation tooling (absent), `host.docker.internal` reachability (proven broken), `qwen2.5:7b` behaviour (never run) |

## 9. Groundedness limitations (stated plainly)

Because no groundedness checker exists in this repo, there is nothing to audit.
Two honest points about what such a checker can and cannot do, for whoever builds it:

- A **numeric** check (does every number in the reply appear in the authoritative
  payload?) catches invented figures and is cheap. It does **not** catch a fluent,
  number-free causal claim — e.g. "the customer is leaving because of the
  suspension" when the data shows only correlation. That failure mode must be
  labelled a limitation in the UI, not papered over.
- Rejecting a reply merely because it contains no *unknown* numbers is not a
  safety property. The current product already refuses to show unvalidated text;
  any future AI panel must keep that refusal.

## 10. Blockers and owner actions

**Blockers (cannot be resolved from inside this environment):**

1. The AI integration does not exist here. If it was built elsewhere, its branch
   or commit was never pushed to `Pixelminds-hub/aeza-analizer` — the repo has
   five branches, zero PRs, and no AI commit. **Owner action:** push the branch or
   provide the commit SHA / repository.
2. No Ollama server and no model. **Owner action:** install and pull, e.g.
   ```
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull qwen2.5:7b          # ~4.7 GB
   ollama serve                    # listens on 127.0.0.1:11434
   ```
   Disk and RAM measured above are sufficient. This was **not** executed here.
3. `host.docker.internal` will not resolve on this Linux host. **Owner action:**
   add to the AI service in `docker-compose.yml`:
   ```yaml
   extra_hosts:
     - "host.docker.internal:host-gateway"
   ```
   or point the container at the host's bridge address directly.

**Owner decisions:**

- Whether the analyst may be enabled by default (the brief says it must not be).
- Which provider abstraction to use — `docs/AI_ANALYST_PLAN.md` §3.1 proposes
  mirroring the existing `AEZA_ANALYTICS_FACTORY` provider pattern.

## 11. What was changed in this pass

Only this file was added. No source, config, `.env`, compose, nginx, volume,
database or secret was modified. No commit, push, PR or deploy was performed.

Files touched this session: `docs/audits/ai-release-gate.md` (new).

### Note for the next person: `openapi.json` has an uncommitted regeneration

While checking OpenAPI drift I ran `git checkout -- backend/openapi.json`, which
reverted an uncommitted change that was **not** mine. I caught it, re-ran
`backend/scripts/export_openapi.py`, and verified the result is byte-identical to
the original worktree content (`diff -q` against a copy taken beforehand → no
difference). Nothing was lost.

Worth knowing, because it will bite anyone else: `backend/openapi.json` is
committed but currently differs from HEAD by 735 insertions / 16 deletions. The
entire diff is the Starlette version's 422 description string,
`"Unprocessable Entity"` → `"Unprocessable Content"`. So the committed file was
generated with an older Starlette than the one installed in this environment.
Regenerating is deterministic and safe, but it is a *real* pending change — do not
`git checkout` it away, and expect a 751-line diff if you regenerate.
