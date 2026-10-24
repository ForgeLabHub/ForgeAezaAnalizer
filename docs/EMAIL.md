# Отправка почты: Yandex Cloud Postbox и SMTP.BZ

Приложение отправляет письма через один из двух провайдеров, выбранный
переменной `AEZA_EMAIL_PROVIDER`. Это единственное место в продукте, которое
обращается к почтовому провайдеру; аналитика, риск и выручка почту не
отправляют. Обе транспортные реализации живут в
`backend/app/integrations/email.py` и используют один контракт, поэтому
дублирующей системы нет.

| Провайдер | Транспорт | Роль |
| --- | --- | --- |
| Yandex Cloud Postbox | SMTP `postbox.cloud.yandex.net`, 465 (TLS) / 587 (STARTTLS) | Управляемый по умолчанию |
| SMTP.BZ | HTTP API `POST https://api.smtp.bz/v1/smtp/send` | Явная альтернатива |

## Выбор провайдера

`Settings.active_email_provider` вычисляется один раз и детерминированно:

- `AEZA_EMAIL_PROVIDER=postbox` — только Postbox; без его учётных данных почта
  выключена (никакого «тихого» переключения на SMTP.BZ);
- `AEZA_EMAIL_PROVIDER=smtp.bz` — только SMTP.BZ, по той же логике;
- пусто или `auto` — Postbox, если он настроен, иначе SMTP.BZ.

Переключения во время выполнения **нет**: подтверждение отправки может прийти
только от того провайдера, который реально использовался, поэтому ложный
`accepted: true` невозможен. Неизвестное имя провайдера отклоняется при старте.

## Что реализовано

| Компонент | Путь | Назначение |
| --- | --- | --- |
| Клиент провайдеров | `backend/app/integrations/email.py` | Диспетчер, SMTP-транспорт Postbox и HTTP-клиент SMTP.BZ |
| Адаптер OTP | `backend/app/integrations/email.py` (`SmtpBzEmailProvider`) | Реализует `EmailProvider.send_otp` из Telegram-модуля |
| Настройки | `backend/app/config.py` | `POSTBOX_*`, `SMTP_BZ_*`, `AEZA_EMAIL_PROVIDER` |
| HTTP-роуты | `backend/app/api/routes_email.py` | `GET /api/v1/email/status`, `POST /api/v1/email/test` |

## Контракт Yandex Cloud Postbox

Из официальной инструкции `https://yandex.cloud/ru/docs/postbox/quickstart`:

- сервер `postbox.cloud.yandex.net`, порт `465` (implicit TLS) или `587` (STARTTLS);
- имя пользователя — идентификатор API-ключа, пароль — его секретная часть;
- требуемая область ключа — `yc.postbox.send`;
- адрес отправителя должен принадлежать домену, привязанному к Postbox.

Пароль аккаунта Яндекса вместо API-ключа не используется; сетевые ограничения
не обходятся.

## Контракт SMTP.BZ

Из Swagger SMTP.BZ (`https://docs.smtp.bz/#/api`, база `https://api.smtp.bz/v1`):

- метод `POST https://api.smtp.bz/v1/smtp/send`;
- ключ API передаётся в заголовке `Authorization` **без** префикса `Bearer`;
- обязательные поля тела: `from`, `subject`, `to`, `html`; необязательные —
  `name`, `to_name`, `reply`, `text`, `tag`.

## Переменные окружения

| Переменная | Обязательна | Назначение |
| --- | --- | --- |
| `AEZA_EMAIL_PROVIDER` | нет | `postbox`, `smtp.bz` или пусто (авто) |
| `POSTBOX_SMTP_USERNAME` | для Postbox | Идентификатор API-ключа |
| `POSTBOX_SMTP_PASSWORD` | для Postbox | Секретная часть API-ключа |
| `POSTBOX_SMTP_HOST` | нет | По умолчанию `postbox.cloud.yandex.net` |
| `POSTBOX_SMTP_PORT` | нет | `465` (TLS) или `587` (STARTTLS), по умолчанию `465` |
| `POSTBOX_FROM_EMAIL` | для Postbox | Адрес отправителя на домене, привязанном к Postbox |
| `POSTBOX_FROM_NAME` | нет | Отображаемое имя отправителя |
| `POSTBOX_TIMEOUT_SECONDS` | нет | Тайм-аут, по умолчанию `15`, допустимо 1–120 |
| `SMTP_BZ_API_KEY` | для SMTP.BZ | Ключ API из раздела «Мой профиль» |
| `SMTP_BZ_FROM_EMAIL` | для SMTP.BZ | Адрес отправителя на верифицированном домене |
| `SMTP_BZ_FROM_NAME` | нет | Отображаемое имя отправителя |
| `SMTP_BZ_API_URL` | нет | По умолчанию `https://api.smtp.bz/v1/smtp/send` |
| `SMTP_BZ_TIMEOUT_SECONDS` | нет | Тайм-аут, по умолчанию `15`, допустимо 1–120 |

Секреты читаются только из окружения. Они не попадают в исходники, Git, образ,
логи и ответы API: `GET /api/v1/email/status` сообщает лишь `keyPresent`.

Если активный провайдер не настроен, отправка выключена:
`GET /api/v1/email/status` возвращает `"configured": false`, а
`POST /api/v1/email/test` отвечает `503`, не выдавая себя за успешную отправку.

## Безопасная проверка

`GET /api/v1/email/status` требует Bearer-токен аналитика и показывает
конфигурацию без секрета:

```bash
curl -sS http://localhost:8000/api/v1/email/status \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Тестовая отправка идёт **только** на явно указанный адрес и требует
`confirm: true` — без него запрос отклоняется с `422` ещё до обращения к
провайдеру:

```bash
curl -sS -X POST http://localhost:8000/api/v1/email/test \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to":"выш-адрес@example.com","confirm":true}'
```

Используйте свой контролируемый ящик. Ответ `200` с `"accepted": true` означает,
что провайдер подтвердил приём письма; факт доставки подтверждает только
получатель. Реальные письма клиентам без разрешения не отправляйте.

## Обработка ошибок

| Ситуация | Класс | HTTP |
| --- | --- | --- |
| Учётные данные или отправитель не заданы | `EmailDisabled` | 503 |
| Провайдер отклонил ключ, отправителя или письмо | `EmailRejected` | 502 |
| Тайм-аут, сеть, 429 и 5xx провайдера | `EmailUnavailable` | 503 |

Сообщение об успехе возвращается только при подтверждении провайдера. Для
SMTP.BZ ответ `2xx`, в теле которого провайдер явно отрицает отправку
(`result: false` или `error`), считается отказом. Для Postbox подтверждение —
ответ `250` на `DATA`; отказ на этапе `MAIL FROM` (например, неподтверждённый
домен) приходит как `SMTPSenderRefused` и превращается в `EmailRejected`. При
тайм-ауте клиент делает **ровно одну** попытку: исход неизвестен, поэтому
слепой повтор не выполняется (риск дубля письма).

## OTP для Telegram-бота

Telegram-сценарий вызывает `email_provider.send_otp(email, code, expires_in_seconds)`
и перехватывает два исключения: `IntegrationNotConfigured` и `DeliveryError`.
Класс `SmtpBzEmailProvider` в `backend/app/integrations/email.py` реализует этот
контракт поверх активного провайдера, поэтому OTP можно отправлять без обхода
существующей логики `TelegramService`.

Адаптер включается автоматически в `create_app` (`backend/app/main.py`), но
только когда активный провайдер настроен (`settings.email_configured`). Если
учётных данных нет, `TelegramService` использует заглушку
`UnconfiguredEmailProvider`, и OTP не отправляется — успех не подделывается.

Подключение в `backend/app/main.py`:

```python
from backend.app.integrations.email import SmtpBzEmailProvider

# внутри create_app(...), перед созданием TelegramService:
otp_provider = email_provider
if otp_provider is None and settings.email_configured:
    otp_provider = SmtpBzEmailProvider(settings)
telegram = TelegramService(database, storage, settings, otp_provider, telegram_provider)
```

## Что остаётся сделать в панели Yandex Cloud

Отправка через Postbox не заработает, пока в Yandex Cloud не выполнены внешние
требования (они не изменяются кодом и не обходятся):

1. Привязать домен `pixel-minds.ru` к Postbox и создать адрес отправителя.
2. Включить Easy DKIM и добавить **обе** выданные CNAME-записи в DNS-зону
   `pixel-minds.ru`.
3. Выпустить API-ключ с областью `yc.postbox.send` для сервисного аккаунта,
   имеющего право на отправку, и поместить его идентификатор/секрет в
   `POSTBOX_SMTP_USERNAME`/`POSTBOX_SMTP_PASSWORD`.

## Что остаётся сделать в панели SMTP.BZ

Если выбран SMTP.BZ, отправка не заработает, пока в панели не выполнены внешние
требования (они не изменяются кодом и не обходятся):

1. Добавить и верифицировать домен отправителя в разделе «Домены отправителя»
   (`https://smtp.bz/panel/domain`).
2. Убедиться, что исходящий IP сервера приложения разрешён в списке IP SMTP.BZ.
3. Проверить, что в профиле выпущен ключ API (`https://smtp.bz/panel/user`).

Если провайдер отвечает отказом из-за неподтверждённого домена, приложение
сообщает об ошибке (HTTP 502 с текстом провайдера) и **не** пытается обойти
проверку.
