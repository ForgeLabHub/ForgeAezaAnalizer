# Telegram bot: configuration, runbook and contract

The bot is a **client-facing** surface: a customer links a Telegram account to an
Aéza account by email OTP, then sees their balance and services in a Mini App and
can talk to support. It is separate from the analyst panel and from the analyst
API. It is **off by default** and never turns itself on.

## 1. Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `AEZA_TELEGRAM_BOT_ENABLED` | `0` | Master switch. `0` ⇒ no Bot API calls, webhook answers `503`. |
| `AEZA_TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather. Required when enabled. |
| `AEZA_TELEGRAM_WEBHOOK_SECRET` | — | Secret Telegram echoes in `X-Telegram-Bot-Api-Secret-Token`. Required when enabled. |
| `AEZA_TELEGRAM_MINI_APP_URL` | — | Public HTTPS URL of the Mini App (`https://<host>/mini-app`). |
| `AEZA_TELEGRAM_WEBHOOK_URL` | — | Public HTTPS URL of `https://<host>/api/v1/telegram/webhook`. Must be HTTPS. |
| `AEZA_TELEGRAM_AUTH_MAX_AGE_SECONDS` | `86400` | Maximum age of Mini App `initData`. |
| `AEZA_TELEGRAM_SESSION_TTL_SECONDS` | `3600` | Client session lifetime. |
| `AEZA_TELEGRAM_OTP_TTL_SECONDS` | `600` | One-time code lifetime. |
| `AEZA_TELEGRAM_OTP_RESEND_SECONDS` | `60` | Minimum gap between code sends. |
| `AEZA_TELEGRAM_OTP_MAX_ATTEMPTS` | `5` | Wrong-code attempts before the code is consumed. |
| `AEZA_TELEGRAM_WORKER_INTERVAL_SECONDS` | `180` | Background worker tick. |

Strict validation: enabling the bot without a token or a webhook secret raises at
startup; a non-HTTPS `AEZA_TELEGRAM_WEBHOOK_URL` is refused. A malformed bot
configuration is an operator error and must be fixed, not started half-configured.

## 2. Check the configuration

```bash
# Compose resolves the environment without starting anything.
POSTGRES_PASSWORD=x docker compose config | grep -i telegram

# The API reports its own view (never the token or the secret).
curl -s localhost:8000/api/v1/telegram/diagnostics -H "Authorization: Bearer $ACCESS_TOKEN" | jq
```

`diagnostics` returns `enabled`, `tokenConfigured`, `webhookSecretConfigured`,
`miniAppUrlConfigured`, and — with the bot on — the live `getMe` identity and the
`getWebhookInfo` state. It never returns the token or the secret.

## 3. Register the webhook (public HTTPS required)

Telegram only delivers to a public HTTPS endpoint. Registration is an explicit
operator action, **not** automatic on startup, so a restart cannot race another
instance or drop pending updates.

```bash
# On the host, set the public URL (never commit it):
#   AEZA_TELEGRAM_WEBHOOK_URL=https://aeza-sentinel.pixel-minds.ru/api/v1/telegram/webhook
docker compose up -d api

curl -s -X POST localhost:8000/api/v1/telegram/webhook/register \
  -H "Authorization: Bearer $ACCESS_TOKEN" | jq
# -> {"registered": true, "url": "https://.../api/v1/telegram/webhook", "pendingUpdateCount": 0}
```

## 4. Verify the bot and the webhook

```bash
# Never paste the token into a shell that keeps history; read it from the host env.
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | jq '.result.username'
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" | jq '.result.url, .result.pending_update_count, .result.last_error_message'
```

A safe test message (no customer data) can be sent from a linked chat by writing
`/start` to the bot. There is no endpoint that sends arbitrary text.

## 5. Logs without leaking the token

```bash
docker compose logs api | grep -i telegram
```

The provider strips the token (and the `…/bot<token>/…` URL) from every error
before it is raised, and deliberately does not chain the original `HTTPError`, so
neither a traceback nor `logger.exception` can print it.

## 6. Disable the bot

```bash
# In the host .env:  AEZA_TELEGRAM_BOT_ENABLED=0
docker compose up -d api
# The webhook then answers 503; the rest of the product is unaffected.
```

## 7. Diagnostics of common failures

| Symptom | Cause | Action |
| --- | --- | --- |
| Webhook answers `503` | `AEZA_TELEGRAM_BOT_ENABLED=0` | Enable and restart. |
| Webhook answers `403` | Wrong/missing secret header | Re-check `AEZA_TELEGRAM_WEBHOOK_SECRET` on both sides. |
| `diagnostics.webhook.url` is `null` | Webhook never registered | `POST /telegram/webhook/register`. |
| Bot receives nothing | No public HTTPS, or wrong URL | Fix `AEZA_TELEGRAM_WEBHOOK_URL`; Telegram rejects HTTP. |
| `«Отправка кода не подключена»` | OTP email provider not configured | See §9 — blocked on the partner contract. |
| Replies marked `failed` | Bot API unreachable | Check `getWebhookInfo.last_error_message`; retries are automatic. |

## 8. OTP e-mail contract (blocked on the partner API)

The plan says the code is delivered by the partner's mail service (`smpt.bz`). The
Telegram service calls a single seam, `EmailProvider.send_otp(email, code,
expires_in_seconds)`, and never talks to the provider directly.

- **Production**: `UnconfiguredEmailProvider` raises `IntegrationNotConfigured`,
  the bot answers "отправка кода не подключена", and **no code is ever
  pretended to have been sent**.
- **Tests**: a recording fake is injected. A mock is never the production path.

To enable it, wire the existing SMTP.BZ client (`backend/app/integrations/email.py`)
behind `EmailProvider` once the contract is agreed — that is the email agent's
file and is not modified here.

## 9. Business rules still needing confirmation

These are recorded, not guessed (see `TELEGRAM_BOT_PLAN.md` "Нюансы"):

1. `suspended`: send a payment reminder after 3 days?
2. `prolong_wait`: daily reminders for the 5-day window?
3. A separate service-expiry reminder when `autoProlong=false`?

The first version notifies **only** `status=active` with `autoProlong=true`, for
`expiresAt - 7d` and `expiresAt - 3d`. `deleted`/`blocked` are never notified.
