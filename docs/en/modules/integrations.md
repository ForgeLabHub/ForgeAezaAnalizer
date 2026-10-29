# Module: external integrations (e-mail, Telegram, snapshot)

English version of [../../modules/integrations.md](../../modules/integrations.md).

## 1. Purpose and boundaries

Optional channels: SMTP e-mail, the Telegram Mini App/bot, and snapshot ingestion from a
source. Every channel is enabled separately and does not affect the analytics.
It is not a mandatory data path and never blocks the start.

## 2. Use scenarios

- Sending a report e-mail (`integrations/email.py`).
- Signing in to the Mini App through the Telegram signature and a one-time code.
- Ingesting a new snapshot by token.
- Failure: a channel is not configured → the operation reports "not configured" and the
  service keeps working.

## 3. Contract

`/api/v1/email/*`, `/api/v1/telegram/*`, `PUT /api/v1/source/snapshot` — in
`backend/openapi.json`. Telegram providers — `telegram/providers.py`.

## 4. Data

No tables of its own. Telegram sessions and OTP live in memory or a cache with TTL
(`AEZA_TELEGRAM_SESSION_TTL_SECONDS`, `AEZA_TELEGRAM_OTP_TTL_SECONDS`); this is deliberate:
an OTP must not survive a restart.

## 5. Access rules

The snapshot — `AEZA_SOURCE_INGEST_TOKEN` (constant-time comparison). Telegram — signature
verification and maximum data age (`AEZA_TELEGRAM_AUTH_MAX_AGE_SECONDS`), plus an OTP
attempt limit. E-mail — authenticated users only.

## 6. Dependencies

Outgoing: an SMTP server, the Telegram Bot API. External systems are isolated behind
adapters, so replacing a provider does not touch the domain.

## 7. Configuration

`AEZA_TELEGRAM_BOT_ENABLED`, `AEZA_TELEGRAM_BOT_TOKEN`, `AEZA_TELEGRAM_WEBHOOK_SECRET`,
`AEZA_TELEGRAM_WEBHOOK_URL`, `AEZA_TELEGRAM_MINI_APP_URL`, `AEZA_TELEGRAM_OTP_*`,
`AEZA_SOURCE_INGEST_TOKEN`, SMTP settings. An empty token means the channel is off.

## 8. Build and debug

```bash
python -m pytest backend/tests/test_email.py -q
python -m pytest backend/tests -q -k telegram
```

## 9. Tests

`test_email.py` (including `aiosmtpd` scenarios), the Telegram tests in `backend/tests`, and
`test_api.py` for the snapshot routes. Refusal without configuration is checked explicitly.

## 10. Observability

Channel errors are logged without secrets (enforced by `check_docs.py` for "secret-like"
examples and by the logging code). Operator action: check that tokens exist and that the
external service is reachable.

## 11. Limitations and readiness

- Telegram session state is in memory: several replicas would need shared storage (not
  supported today).
- No retry queue for e-mail.
- Readiness: any channel can be switched off and the product keeps working.
