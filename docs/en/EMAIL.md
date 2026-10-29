# E-mail

English version of [../EMAIL.md](../EMAIL.md).

The application supports Yandex Cloud Postbox and SMTP.BZ. The provider is chosen with
`AEZA_EMAIL_PROVIDER`: `postbox`, `smtp.bz`, or an empty value to pick the configured
provider automatically.

For Postbox set `POSTBOX_SMTP_USERNAME`, `POSTBOX_SMTP_PASSWORD` and
`POSTBOX_FROM_EMAIL`. For SMTP.BZ set `SMTP_BZ_API_KEY` and `SMTP_BZ_FROM_EMAIL`. The
sender and timeout settings are listed in `.env.example`.

The configuration state can be checked through the authorised `GET /api/v1/email/status`.
A controlled test message is sent through `POST /api/v1/email/test`; use an address you can
access and confirm the sending in the request body.

Keep e-mail secrets in the environment. If the selected provider is not configured, the
application does not send mail.
