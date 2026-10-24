# Telegram bot + Mini App: deployment and @BotFather runbook

Target stand: `https://aeza-sentinel.pixel-minds.ru` (host `aezka`, `158.160.212.225`).
Bot: **@aezasentinelbot**. Published commit: `787f37b`.

## 0. Current stand state (measured, not assumed)

| Check | Result |
| --- | --- |
| `https://aeza-sentinel.pixel-minds.ru/` | `200` — serves the SPA |
| `https://pixel-minds.ru/` | `200` — **identical** SPA (same ETag) |
| `/health`, `/ready`, `/api/v1/openapi.json` | **`502`** |
| `/mini-app` | `200` (SPA fallback) |

So the `web` container answers and the **`api` container is down** (nginx
`upstream aeza_api { server api:8000; }` has no live upstream). Everything that
proxies to `/api/…` therefore returns 502. This is an operational problem on the
server, not a code problem: the same commit runs healthy locally
(`api`, `db`, `web` all `Up (healthy)`, `/health` 200).

Two routing facts also worth confirming on the host nginx, because they would
each produce a 502 on their own:

1. `/api/…` must be proxied to the **`web`** container's port 80 (which itself
   proxies `/api/` to `api:8000`), **or** straight to `api:8000`. A proxy to a
   wrong port, or to `127.0.0.1:8000` when only the container listens, gives 502.
2. The host nginx `server_name` must match `aeza-sentinel.pixel-minds.ru`; both
   domains currently serve the same content, which suggests one default server
   block is answering for both.

## 1. Bring the API back (fixes the 502)

On the server, in the project directory (`~/aeza-analizer`):

```bash
cd ~/aeza-analizer
git fetch origin && git log --oneline -1 origin/main      # expect 787f37b
docker compose ps                                          # which services are up?
docker compose logs --tail=100 api                         # the real reason it is down
```

Then, once the log shows the cause (most often a bad `POSTGRES_PASSWORD`, a
missing required env, or a failed migration):

```bash
git pull --ff-only origin main
docker compose up -d --build api web
docker compose ps
curl -fsS localhost:8000/health && echo && curl -fsS localhost:8000/ready && echo
```

Do **not** run `docker compose down -v`: it deletes the `pg_data` and `auth_data`
volumes. `up -d --build` recreates only the changed containers.

If the API log shows a configuration error from `.env`, fix that one variable
(after `cp .env .env.bak.$(date -u +%Y%m%dT%H%M%SZ)`) and re-run `up -d`.

## 2. Telegram configuration in the server `.env`

Back up first, then set these. The token is read from the environment only and is
never printed:

```bash
cd ~/aeza-analizer
cp .env .env.bak.$(date -u +%Y%m%dT%H%M%SZ)

# Generate the webhook secret without echoing it.
python3 - <<'PY' >> .env
import secrets
print("AEZA_TELEGRAM_WEBHOOK_SECRET=" + secrets.token_urlsafe(32))
PY

# Edit the rest by hand (or with an editor) — never paste the token into shell history:
#   AEZA_TELEGRAM_BOT_ENABLED=1
#   AEZA_TELEGRAM_BOT_TOKEN=<the @aezasentinelbot token from @BotFather>
#   AEZA_TELEGRAM_MINI_APP_URL=https://aeza-sentinel.pixel-minds.ru/mini-app
#   AEZA_TELEGRAM_WEBHOOK_URL=https://aeza-sentinel.pixel-minds.ru/api/v1/telegram/webhook

docker compose up -d api
```

`AEZA_TELEGRAM_WEBHOOK_URL` must be `https://`; a non-HTTPS value fails startup on
purpose (Telegram refuses HTTP webhooks).

## 3. Verify the bot without leaking the token

Run these on the server. `getMe` and `getWebhookInfo` print only safe fields:

```bash
cd ~/aeza-analizer
set -a; . ./.env; set +a

# Identity — only the username is printed.
curl -s "https://api.telegram.org/bot${AEZA_TELEGRAM_BOT_TOKEN}/getMe" \
  | python3 -c 'import sys,json; r=json.load(sys.stdin)["result"]; print("bot:", r["username"], "id:", r["id"])'

# Webhook state — the URL and pending count, never the secret.
curl -s "https://api.telegram.org/bot${AEZA_TELEGRAM_BOT_TOKEN}/getWebhookInfo" \
  | python3 -c 'import sys,json; r=json.load(sys.stdin)["result"]; print("url:", r.get("url")); print("pending:", r.get("pending_update_count")); print("last_error:", r.get("last_error_message"))'
```

Then register the webhook through the app (not by hand), which reads back
Telegram's own view:

```bash
# Analyst token first (the endpoint is bearer-protected):
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"<analyst login>","password":"<password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST localhost:8000/api/v1/telegram/webhook/register -H "Authorization: Bearer $TOKEN"
# -> {"registered": true, "url": "https://aeza-sentinel.pixel-minds.ru/api/v1/telegram/webhook", ...}

curl -s localhost:8000/api/v1/telegram/diagnostics -H "Authorization: Bearer $TOKEN"
# -> enabled/tokenConfigured/webhookSecretConfigured + the live bot identity.
#    It never contains the token or the secret.
```

## 4. @BotFather setup (manual — cannot be automated without the token)

These are Telegram-side settings only the owner can apply:

1. `/mybots` → **@aezasentinelbot** → **Edit Bot**.
2. **Edit Botpic** → upload `docs/telegram/bot-avatar-512.png`.
3. **Edit Description** → short text, e.g.
   «Aéza Sentinel — личный кабинет клиента: баланс, услуги, поддержка.»
4. **Edit About** → «Проверка баланса и услуг Aéza и связь с поддержкой.»
5. **Edit Commands** → set exactly the commands the bot implements:
   ```
   start - Начать и привязать аккаунт
   help - Справка
   status - Статус привязки
   cancel - Отменить текущий шаг
   rebind - Привязать другой email
   digest - Ежедневная сводка вкл/выкл
   ```
6. **Bot Settings → Menu Button → Configure menu button** → URL:
   `https://aeza-sentinel.pixel-minds.ru/mini-app`
   (this is the button that opens the Mini App).
7. Optional: **Bot Settings → Domain** → `aeza-sentinel.pixel-minds.ru`.

The avatar can be set through the API instead, if the owner prefers to script it:

```bash
curl -s -F "photo=@docs/telegram/bot-avatar-512.png" \
  "https://api.telegram.org/bot${AEZA_TELEGRAM_BOT_TOKEN}/setMyPhoto" \
  | python3 -c 'import sys,json; print("ok:", json.load(sys.stdin)["ok"])'
```

## 5. Mini App checks

Inside Telegram, open the bot and tap the menu button. The Mini App:

- loads the Telegram Web App SDK (`telegram-web-app.js`);
- exchanges the signed `initData` for a client session
  (`POST /api/v1/client/session`) — the server verifies the HMAC and `auth_date`
  and derives the account from the stored link, so the client never sends an
  account id;
- shows the balance (or «нет данных» when absent), the service list and the
  support thread; it deliberately never shows risk scores, risk reasons or
  analyst recommendations.

In a plain browser the same URL explains that it must be opened from Telegram,
which is the expected behaviour rather than an error.

## 6. Known external blockers

- **SMTP.BZ OTP**: the provider rejected a letter because the sender domain
  `pixel-minds.ru` is not activated in the SMTP.BZ panel. Until the owner
  activates it, the bot answers «отправка кода не подключена» and sends nothing —
  it never reports a fake success. Activation is a panel action by the owner.
- **SSH**: the agent has no key for `aezka`, so every server step above is
  prepared, not executed. Add the agent's public key to
  `~/.ssh/authorized_keys` (or hand over a deploy key) to let it run them.
