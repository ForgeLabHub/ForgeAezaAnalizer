# Telegram Mini App and bot

English version of [../TELEGRAM_BOT.md](../TELEGRAM_BOT.md).

Telegram features are disabled by default. To enable them, create a bot through BotFather
and set in `.env`:

```dotenv
AEZA_TELEGRAM_BOT_ENABLED=1
AEZA_TELEGRAM_BOT_TOKEN=...
AEZA_TELEGRAM_WEBHOOK_SECRET=...
AEZA_TELEGRAM_MINI_APP_URL=https://app.example.com/mini-app
AEZA_TELEGRAM_WEBHOOK_URL=https://app.example.com/api/v1/telegram/webhook
```

The webhook must be reachable at a public HTTPS address. A one-time code e-mail is sent only
when a mail provider is configured; see the e-mail guide ([EMAIL.md](EMAIL.md)).

After the API starts, register the webhook with an authorised request:

```bash
curl -X POST http://localhost:8000/api/v1/telegram/webhook/register -H "Authorization: Bearer $ACCESS_TOKEN"
```

The state is available through `GET /api/v1/telegram/diagnostics`. The remaining parameters,
including session and one-time-code lifetimes, are listed in `.env.example`.

## Mini App

After entering the e-mail and the code the bot offers to enable reminders and shows a button
to open the Mini App. On the first open the Telegram Mini App exchanges the signed Telegram
data for a client session automatically — no code needs to be entered again. The Mini App
offers account data, services, reminder settings and a support conversation. An open support
screen refreshes every 10 seconds.
