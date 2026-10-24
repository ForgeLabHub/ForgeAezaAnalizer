# Отправка почты через SMTP.BZ

Приложение отправляет письма через HTTP API SMTP.BZ. Это единственное место
в продукте, которое обращается к почтовому провайдеру; аналитика, риск и
выручка почту не отправляют.

## Что уже реализовано

| Компонент | Путь | Назначение |
| --- | --- | --- |
| Клиент провайдера | `backend/app/integrations/email.py` | Один вызов `POST …/v1/smtp/send`, разбор ответа и ошибок |
| Адаптер OTP | `backend/app/integrations/email.py` (`SmtpBzEmailProvider`) | Реализует `EmailProvider.send_otp` из Telegram-модуля |
| Настройки | `backend/app/config.py` | Переменные `SMTP_BZ_*` и признак `email_configured` |
| HTTP-роуты | `backend/app/api/routes_email.py` | `GET /api/v1/email/status`, `POST /api/v1/email/test` |

До этого изменения почтовой логики в проекте не было, поэтому дублирующая
система не создавалась — клиент добавлен как новый изолированный модуль.

## Контракт провайдера

Из официального Swagger SMTP.BZ (`https://docs.smtp.bz/#/api`, база
`https://api.smtp.bz/v1`):

- метод `POST https://api.smtp.bz/v1/smtp/send`;
- ключ API передаётся в заголовке `Authorization` **без** префикса `Bearer`;
- обязательные поля тела: `from`, `subject`, `to`, `html`; необязательные —
  `name` (имя отправителя), `to_name`, `reply`, `text`, `tag`;
- провайдер принимает и `application/json`, и `multipart/form-data`; приложение
  использует JSON.

## Переменные окружения

| Переменная | Обязательна | Назначение |
| --- | --- | --- |
| `SMTP_BZ_API_KEY` | да | Ключ API из раздела «Мой профиль» панели SMTP.BZ |
| `SMTP_BZ_FROM_EMAIL` | да | Адрес отправителя на **верифицированном** домене |
| `SMTP_BZ_FROM_NAME` | нет | Отображаемое имя отправителя |
| `SMTP_BZ_API_URL` | нет | По умолчанию `https://api.smtp.bz/v1/smtp/send` |
| `SMTP_BZ_TIMEOUT_SECONDS` | нет | Тайм-аут запроса, по умолчанию `15`, допустимо 1–120 |

Ключ читается только из окружения. Он не попадает в исходники, Git, образ,
логи и ответы API: `GET /api/v1/email/status` сообщает лишь `keyPresent`.

Если `SMTP_BZ_API_KEY` или `SMTP_BZ_FROM_EMAIL` пусты, отправка выключена:
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
| Ключ или отправитель не заданы | `EmailDisabled` | 503 |
| Провайдер отклонил ключ (401/403) или письмо (4xx, отказ в теле) | `EmailRejected` | 502 |
| Тайм-аут, сеть, 429 и 5xx провайдера | `EmailUnavailable` | 503 |

Сообщение об успехе возвращается только при подтверждении провайдера. Ответ `2xx`,
в теле которого провайдер явно отрицает отправку (`result: false` или `error`),
считается отказом, а не успехом. При тайм-ауте клиент делает **ровно одну** попытку:
исход неизвестен, поэтому слепой повтор не выполняется (риск дубля письма).

## OTP для Telegram-бота

Telegram-сценарий вызывает `email_provider.send_otp(email, code, expires_in_seconds)`
и перехватывает два исключения: `IntegrationNotConfigured` и `DeliveryError`.
Класс `SmtpBzEmailProvider` в `backend/app/integrations/email.py` реализует этот
контракт поверх SMTP.BZ, поэтому OTP можно отправлять без обхода существующей
логики `TelegramService`.

Адаптер **не включается автоматически**. Пока интегратор не передал его в
`create_app(email_provider=...)`, `TelegramService` использует заглушку
`UnconfiguredEmailProvider`, и OTP не отправляется (как и требует текущее
соглашение: OTP выключен до согласования контракта партнёрского API).

Подключение выполняет интегратор Telegram-модуля — в `backend/app/main.py`:

```python
from backend.app.integrations.email import SmtpBzEmailProvider

# внутри create_app(...), перед созданием TelegramService:
if email_provider is None and settings.email_configured:
    email_provider = SmtpBzEmailProvider(settings)
```

Это единственное изменение общей сборки, которое требуется для OTP. Оно не
включает OTP само по себе — включается лишь транспорт, когда заданы `SMTP_BZ_*`.

## Что остаётся сделать в панели SMTP.BZ

Отправка не заработает, пока в панели SMTP.BZ не выполнены внешние требования
(они не изменяются кодом и не обходятся):

1. Добавить и верифицировать домен отправителя в разделе «Домены отправителя»
   (`https://smtp.bz/panel/domain`). Адрес из `SMTP_BZ_FROM_EMAIL` должен
   принадлежать именно этому домену.
2. Убедиться, что исходящий IP сервера приложения разрешён в списке IP
   SMTP.BZ. Существующий allowlist менять не нужно; при отказе — добавить IP.
3. Проверить, что в профиле выпущен ключ API (`https://smtp.bz/panel/user`) и он
   совпадает с `SMTP_BZ_API_KEY`.

Если провайдер отвечает отказом из-за неподтверждённого домена, приложение
сообщает об ошибке (HTTP 502 с текстом провайдера) и **не** пытается обойти
проверку.
