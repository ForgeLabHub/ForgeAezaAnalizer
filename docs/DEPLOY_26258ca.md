# Deployment runbook — commit `26258ca`

Target: `https://aeza-sentinel.pixel-minds.ru/` (nginx/1.24.0, `158.160.212.225`).

## 1. Blocker: this environment cannot deploy

The agent has **no path to the production host**. Verified, not assumed:

| Check | Result |
| --- | --- |
| `ls ~/.ssh` | no such directory |
| `which ssh scp rsync` | none installed |
| Deploy workflow in `.github/workflows/` | only `ci.yml`; no deploy job |
| `render.yaml` / `Procfile` / `fly.toml` / `vercel.json` | none |
| Credentials for the host in the repo | none |

So **nothing was deployed**, and no claim below is a production result. Every
command here is for the owner to run on the server.

## 2. What the deploy must change

The stand currently answers `404` on `/api/v1/telegram/status`, i.e. it runs an
older build without the Telegram routes. To confirm before deploying:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://aeza-sentinel.pixel-minds.ru/api/v1/telegram/status
# 404 today; 401 after the deploy (401 = route exists and requires auth)
```

## 3. Before deploying

```bash
cd <deploy-dir>
git fetch origin && git log --oneline -1 origin/main     # expect 26258ca
git status --short                                        # expect clean
docker compose config >/dev/null && echo "compose ok"

# Back up the data that a rollback would need. Never use `down -v`.
docker compose exec -T db pg_dump -U aeza -d aeza > ~/aeza-$(date +%F).sql
docker compose exec -T api python - <<'PY'
import sqlite3
s = sqlite3.connect('/app/db/auth.sqlite3'); d = sqlite3.connect('/tmp/auth.bak')
s.backup(d); d.close(); s.close(); print('auth backup ok')
PY
docker compose cp api:/tmp/auth.bak ~/auth-$(date +%F).sqlite3
```

## 4. Environment

Add these to the server's environment (an `.env` file next to
`docker-compose.yml`, or the host's service environment). **Do not paste real
secrets into a chat or a commit.**

```env
# Telegram (all optional; the app runs without them)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_WEBHOOK_SECRET=<python -c "import secrets;print(secrets.token_urlsafe(32))">
TELEGRAM_WEBHOOK_URL=https://aeza-sentinel.pixel-minds.ru/api/v1/telegram/webhook
TELEGRAM_DIGEST_HOUR_UTC=9
TELEGRAM_DIGEST_CHECK_SECONDS=300
```

Keep the existing `AEZA_JWT_SECRET`, `AEZA_ADMIN_EMAIL`, `AEZA_ADMIN_PASSWORD`,
`POSTGRES_PASSWORD`. **Do not confuse these with `AEZA_AI_ENABLED` /
`AEZA_LLM_ENABLED`** — those are the local-LLM switches and are unrelated to
Telegram.

## 5. Deploy

```bash
git pull --ff-only origin main
docker compose build api web
docker compose up -d
docker compose ps            # expect api/db/web healthy
```

## 6. Verify after deploying

```bash
S=https://aeza-sentinel.pixel-minds.ru
curl -s -o /dev/null -w 'health %{http_code}\n' $S/health
curl -s -o /dev/null -w 'telegram/status %{http_code}\n' $S/api/v1/telegram/status   # 401 = present
curl -s $S/api/v1/openapi.json | python3 -c "import sys,json;print([p for p in json.load(sys.stdin)['paths'] if 'telegram' in p])"
```

Then, with an authenticated session in the UI:

1. Open **Telegram** → «Создать код подключения».
2. Send the bot `/start <КОД>`; expect a confirmation.
3. Toggle a notification kind and set a threshold; reload the page and confirm it
   persisted.
4. Press «Отправить тестовое уведомление»; expect the message in Telegram.
5. Register the webhook if the app has not done it:
   `curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" -d url=$TELEGRAM_WEBHOOK_URL -d secret_token=$TELEGRAM_WEBHOOK_SECRET`
6. Check `/api/v1/telegram/diagnostics` for the delivery log.

Also re-check the pre-existing analytics: `/api/v1/analytics/summary` must still
return the same shape, and the dashboard must render.

## 7. Rollback

The Telegram change is **additive**: four new tables created by the existing
`initialize()` call, new routes, new frontend page. No existing column or route
was altered.

```bash
git checkout <previous-commit>
docker compose build api web && docker compose up -d
```

- Safe: the old code ignores the extra tables; no data migration is undone.
- **Do not** run `docker compose down -v` — it destroys the Postgres and auth
  volumes.
- Restoring a database dump is unnecessary unless Telegram data must be removed.

## 8. Still not done (state plainly)

| Item | Status |
| --- | --- |
| Deploy to production | **NOT DONE** — no host access |
| Real Telegram Bot API delivery | **NOT TESTED** — needs a real token; tests use a stub client |
| Real `qwen2.5:7b` through the app | verified earlier from a local install, not on the stand |
| Daily digest on the stand | implemented and unit-tested; not observed in production |
| Rotating the credentials shared in chat | owner action |
