# Telegram integration

Aéza Sentinel can deliver retention alerts to Telegram. The integration is part
of the existing application: it reads the same published calculation the HTTP API
serves and never recomputes risk, money or recommendations. It is **off by
default**, and the app runs normally with no bot token configured.

## What it does

| Command | Behaviour |
| --- | --- |
| `/start` | Explains how to link; `/start <КОД>` redeems a one-time code |
| `/help` | Command list |
| `/status` | Which account the chat is linked to, plus subscriptions and thresholds |
| `/subscribe` | Enable notifications |
| `/unsubscribe` | Disable notifications **and** unlink the chat |
| `/top` | Five highest-risk customers (linked chats only) |
| `/customer <id>` | One customer's score, reasons and recommendations (linked chats only) |
| `/digest on\|off` | Toggle the daily summary |

Notification kinds (each can be toggled per chat in the UI):

- `high_risk` — a customer **moved into** the high-risk category
- `exposure_jump` — revenue at risk grew past the configured euro threshold
- `new_action` — a new retention recommendation appeared
- `data_quality` — a data-quality problem was detected
- `daily_digest` — periodic summary

## Security model

- **A Telegram username is never identity.** A chat is linked only by redeeming a
  one-time code that an authenticated Sentinel user created in the UI.
- **Only the code's SHA-256 hash is stored**, so a database leak does not yield
  usable codes. The plaintext is shown once.
- **Redemption is atomic and single-use.** The code is consumed in the same
  transaction that creates the link, so two concurrent redemptions cannot both
  succeed.
- **A chat cannot be taken over.** `chat_id` is unique in the links table; a code
  for a different account is refused while a chat is bound.
- **Attempts are bounded** (`TELEGRAM_LINK_MAX_ATTEMPTS`), and codes expire
  (`TELEGRAM_LINK_CODE_TTL_SECONDS`).
- **The webhook is authenticated by Telegram's own secret**, compared in constant
  time via `X-Telegram-Bot-Api-Secret-Token`. A wrong or missing secret is 403.
- **No markup injection.** Messages are sent without `parse_mode`, so a customer
  name or reason cannot alter formatting.
- **Data minimisation.** Alerts carry a customer id, a score, a euro figure and a
  reason — never e-mail addresses, balances or raw records.
- **The bot token is read from the environment only** and never appears in the
  database, the API responses, the frontend or the logs.

## Configuration

Set these on the server (see `.env.example` for the full list):

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_WEBHOOK_SECRET=<long random string>
TELEGRAM_WEBHOOK_URL=https://<your-host>/api/v1/telegram/webhook
```

`TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` are required **only** when
`TELEGRAM_ENABLED=true`; otherwise the feature stays dormant and the rest of the
app is unaffected.

## Setting up the bot

1. Talk to [@BotFather](https://t.me/BotFather), run `/newbot`, and copy the token.
2. Generate a webhook secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. Put both in the server environment (never in Git), with
   `TELEGRAM_WEBHOOK_URL` pointing at your public HTTPS host.
4. Restart the API. The tables are created automatically at startup; there is no
   separate migration step, exactly like the other integration tables.
5. Register the webhook — either from the host:

   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<your-host>/api/v1/telegram/webhook" \
     -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>" \
     -d 'allowed_updates=["message"]'
   ```

   or let the app do it (it uses the same values from the environment).

## Using it

1. Sign in to Sentinel and open **Telegram** in the navigation.
2. Press **«Создать код подключения»** and copy the code.
3. Send the bot `/start <КОД>`. The chat is now linked.
4. Choose which notifications to receive and set the thresholds.
5. Press **«Отправить тестовое уведомление»** to prove the path end to end.

To disconnect: **«Отключить Telegram»** in the UI, or `/unsubscribe` in the chat.
Both revoke the link and delete the subscription.

## Local development without a real bot

Everything except actual delivery works with the feature off. To exercise the
HTTP surface without Telegram:

```bash
export TELEGRAM_ENABLED=1 TELEGRAM_BOT_TOKEN=123:TEST TELEGRAM_WEBHOOK_SECRET=whsec
python -m uvicorn main:app --port 8000

# link a chat through the webhook the way Telegram would:
curl -s -X POST localhost:8000/api/v1/telegram/webhook \
  -H 'X-Telegram-Bot-Api-Secret-Token: whsec' \
  -H 'Content-Type: application/json' \
  -d '{"message":{"chat":{"id":9001},"text":"/start <КОД>"}}'
```

The test suite does this against a stub client, so no network is required:
`python -m pytest backend/tests/test_telegram.py -q`.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| UI shows «Интеграция отключена» | `TELEGRAM_ENABLED` is not `true` |
| `503` from `/telegram/link-code` | Same — the feature is off, or the service failed to build (check logs) |
| Webhook returns `403` | `TELEGRAM_WEBHOOK_SECRET` on the server does not match the `secret_token` used in `setWebhook` |
| Webhook returns `200` but nothing happens | The update is malformed, oversized, or the feature is off; a `200` is returned deliberately so Telegram does not retry forever |
| Bot replies «Чат не подключён» | The chat was never linked, or `/unsubscribe` revoked it |
| «Этот чат уже подключён к другому аккаунту» | The chat is bound elsewhere; disconnect it there first |
| Test message fails with `502` | Telegram refused or was unreachable; check the token and the delivery log at `/api/v1/telegram/diagnostics` |

## Disabling

Set `TELEGRAM_ENABLED=false` and restart. The webhook answers `200` without
processing, the management API returns `503`, and existing links remain in the
database but receive nothing. To remove a binding permanently, disconnect it in
the UI first.

## Known limitations

- **No scheduler for the daily digest.** The bot command and the preference are
  implemented and stored, but nothing dispatches the digest on a timer: the
  project has no background-job infrastructure, and adding Redis or Celery for
  one message a day was not justified. `notifications.digest_text()` produces the
  text; a cron entry calling the send path can be added when a scheduler exists.
  This is stated rather than implied by a switch that does nothing.
- **Notifications follow the recalculation clock.** `dispatch_notifications()`
  runs after each scheduled recalculation in `backend/app/main.py`, so alerts
  track new generations. It is deliberately *not* called from the request path,
  so a Telegram outage cannot slow down or fail an API call.
- **Delivery retries are bounded and synchronous** (`TELEGRAM_MAX_RETRIES`).
  They run in the background task, never inside an analytics request.
