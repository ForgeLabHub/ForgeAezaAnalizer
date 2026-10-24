# AI release gate

Date: 2026-10-24. Branch `main`, which now tracks `origin/main`.
Scope: the local AI Analyst (`backend/app/ai/`, `POST /api/v1/ai/*`) and the
aggregate assistant (`backend/app/domain/llm.py`, `POST /api/v1/insights/ai`).

Evidence classes are kept apart on purpose. "Verified with the real model" means
the actual `qwen2.5:7b` answered through the app's HTTP API; "verified with the
mock" means the offline provider; "not verified" means nothing was run.

## 1. Status by evidence class

| Area | Implemented | Unit-tested | HTTP + mock | Real model | Docker | Browser | Production |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AI service, providers, safety | yes | yes | yes | yes | no | yes | no |
| `POST /ai/customers/{id}/explain` | yes | yes | yes | **yes** | no | yes | no |
| `GET /ai/status` | yes | yes | yes | **yes** | no | yes | no |
| Other `/ai/*` routes (chat, scenarios, reports) | yes | yes | yes | partial | no | no | no |
| `POST /insights/ai` (aggregate) | yes | yes | yes | no | no | no | no |
| Grounding verifier (numbers, e-mails) | yes | yes | yes | **yes** | n/a | n/a | n/a |
| CPU timeout budget | yes | yes | n/a | **yes** | no | n/a | no |
| Frontend AI panel | yes | n/a | n/a | yes | no | yes | no |

## 2. What is proven

- **The real model answers through the app.** With `qwen2.5:7b` served by Ollama
  0.40.10 on `127.0.0.1:11434`, `POST /api/v1/ai/customers/10/explain` returned
  **200**, `grounded: true`, and the summary quoted the engine's own 71.40.
  Measured cold 196.6 s / 303.7 s, warm 171.8 s; `promptTokens` 1994,
  `completionTokens` ~470.
- **Failures are honest.** Provider down → **503**; disabled feature → **503**;
  unauthenticated → **401**; unknown customer → **404**; oversized question →
  **422**. No path returns a canned "AI" answer.
- **Read-only.** The published generation is unchanged across explain calls.
- **Injection resisted.** A question instructing the model to ignore its rules
  and output "99 % / 12 345 €" produced neither figure; the model answered that
  the data does not contain them.
- **Defect found and fixed.** The default timeout (180 s) was below the measured
  cold CPU-only cost, so the first request after an Ollama restart returned 503
  for a healthy model. Default is now 420 s with a regression test that fails on
  180 s. Verified with the real model: cold start now returns 200.
- Suites: **312 backend + 69 root = 381 tests**, all passing; `tsc -b` and
  `npm run build` exit 0; `docker compose config` valid.

## 3. Limits that remain (do not overstate)

1. **Qualitative hallucination is not caught.** Numeric/e-mail grounding passes
   an answer that inverts a *fact*. Observed with the real model: the fact block
   said service #10 has auto-renewal **on**, and the model wrote that it is
   **off**, with `grounded: true`. The pipeline cannot detect this; treat the
   text as a draft, not as a source of truth.
2. **CPU-only latency is minutes.** A cold call is ~3–5 min and a warm one
   ~3 min on this 4 vCPU host. The request is synchronous; a user waits.
   A GPU or a smaller model is required for interactive use.
3. **The default model name differs between layers.** `backend/app/ai` defaults
   to `qwen2.5:3b-instruct`, `backend/app/config.py` to `qwen2.5:7b`. Set
   `AEZA_AI_MODEL` explicitly.
4. **No answer cache**, single-turn, no conversation memory.
5. **Two AI layers coexist** (`app/ai/*` for `/ai/*`, `domain/llm.py` for
   `/insights/ai`). Both are tested; they are not unified.
6. **No Docker build was run.** The daemon cannot start in this sandbox
   (`dockerd` + `containerd` conflict), so image build and in-container
   `host.docker.internal` resolution are unverified.
7. **Not deployed.** No production check of any `/api/v1/ai/*` route.

## 4. Resource requirements (measured, not estimated)

| Item | Value |
| --- | --- |
| CPU | 4 vCPU; **no GPU** on this host |
| RAM | 15.6 GiB total, ~5 GiB free before load; model resident ~1.5 GiB + KV cache |
| Disk | Ollama binary ~1.5 GB (tar.zst) + `qwen2.5:7b` 4.68 GB |
| Throughput | ~17 prompt tok/s, ~4 generated tok/s (q4_K_M, CPU) |
| Cold call | ~197–304 s |
| Warm call | ~172 s |

## 5. Exact run commands (verified)

```bash
# 1. Ollama (user-level, no systemd, model store outside the repo tree)
mkdir -p /opt/ollama && cd /opt/ollama
curl -fsSL -o o.tar.zst \
  https://github.com/ollama/ollama/releases/download/v0.40.10/ollama-linux-amd64.tar.zst
python3 -c "import zstandard,tarfile;d=zstandard.ZstdDecompressor();\
f=d.stream_reader(open('o.tar.zst','rb'));tarfile.open(fileobj=f,mode='r|').extractall('.')"
OLLAMA_MODELS=/opt/ollama/models ./bin/ollama serve &
./bin/ollama pull qwen2.5:7b

# 2. The app (repo root)
export AEZA_JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export AEZA_ADMIN_PASSWORD="demo123"
export AEZA_DATABASE_URL="sqlite:///$(pwd)/data/analytics.sqlite"
export AEZA_AUTH_DATABASE_URL="sqlite:///$(pwd)/db/auth.sqlite3"
export AEZA_ANALYTICS_FACTORY="backend.app.domain.module:create"
export AEZA_SEED_DEMO_DATA=1
export AEZA_AI_ENABLED=1 AEZA_AI_PROVIDER=ollama
export AEZA_AI_BASE_URL="http://127.0.0.1:11434" AEZA_AI_MODEL="qwen2.5:7b"
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# 3. Frontend
cd frontend && npm install && npm run dev
```

## 6. Owner actions before publishing

1. Decide which AI layer is the product of record and retire the other, or state
   clearly that both exist.
2. Align the model name across `app/ai/config.py` and `app/config.py`.
3. Set `AEZA_AI_ENABLED` plus the other AI variables explicitly in the deployment environment; do not rely on
   defaults.
4. Confirm the GPU/CPU budget for the demo host; on CPU the first answer takes
   minutes.
5. Build and start with Docker on a machine with a working daemon and confirm the
   container reaches Ollama.
6. Re-run the browser walkthrough after deploy.
7. Keep `AEZA_AI_ENABLED=0` until the above is settled: the UI then explains that
   the model is off and the deterministic analysis keeps working.

## 7. Not verified

- Docker image build; `host.docker.internal` from inside a container.
- Production deployment of any AI route.
- Answer quality for the other `/ai/*` tasks and for `/insights/ai` with the real
  model.
- Behaviour under concurrent AI requests (`max_concurrency` default 1).

## 8. Push status (DONE)

The work was published to `main` once a credential with write access was
supplied by the owner.

```
$ git push https://<token>@github.com/Pixelminds-hub/aeza-analizer.git main
To https://github.com/Pixelminds-hub/aeza-analizer.git
   534ca6c..c6bbff1  main -> main
```

Verified afterwards:

| Check | Result |
| --- | --- |
| `git ls-remote origin refs/heads/main` | `c6bbff19a890540c2b3c47b31d87909e420bc25e` |
| local `HEAD` vs `origin/main` | identical, 0 ahead / 0 behind |
| fast-forward | yes — `origin/main` was an ancestor, no history rewrite |
| force push | none |
| token in `.git/config` | none |
| token in tracked files | none (checked with `git grep`) |
| extra branches pushed | none |

### Why the earlier attempts failed

Both credentials available to the agent authenticate as **`Pavel1778`**, while
the repository is owned by **`Pixelminds-hub`**:

- `GITHUB_TOKEN` (`ghu_…`) is a GitHub App installation token scoped to
  `Pavel1778`'s own repositories. It *can* create refs there (verified: 201) but
  returns `403 Resource not accessible by integration` on `aeza-analizer`.
- `GITHUB_PERSONAL_ACCESS_TOKEN` (`github_pat_…`) is a fine-grained token with no
  write grant; every write returned `403 Resource not accessible by personal
  access token`, even on `Pavel1778`'s own repositories.

The classic token belonging to the repository owner has full `repo` scope and
`admin` on the repository, and the push succeeded with it. It was used only for
this one command and was not stored anywhere.
