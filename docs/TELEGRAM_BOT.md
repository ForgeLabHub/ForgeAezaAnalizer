# Telegram Mini App и бот

Telegram-функции выключены по умолчанию. Для включения создайте бота через BotFather и задайте в .env:

~~~dotenv
AEZA_TELEGRAM_BOT_ENABLED=1
AEZA_TELEGRAM_BOT_TOKEN=...
AEZA_TELEGRAM_WEBHOOK_SECRET=...
AEZA_TELEGRAM_MINI_APP_URL=https://app.example.com/mini-app
AEZA_TELEGRAM_WEBHOOK_URL=https://app.example.com/api/v1/telegram/webhook
~~~

Webhook должен быть доступен по публичному HTTPS-адресу. Письмо с одноразовым кодом отправляется только при настроенном почтовом провайдере; смотрите инструкцию по почте (EMAIL.md).

После запуска API зарегистрируйте webhook авторизованным запросом:

~~~bash
curl -X POST http://localhost:8000/api/v1/telegram/webhook/register -H "Authorization: Bearer $ACCESS_TOKEN"
~~~

Статус доступен через GET /api/v1/telegram/diagnostics. Остальные параметры, включая сроки сессии и одноразового кода, перечислены в .env.example.

## Mini App

После ввода email и кода бот предлагает включить напоминания и показывает кнопку открытия Mini App. При первом открытии в Telegram Mini App автоматически обменивает подписанные данные Telegram на клиентскую сессию — повторный ввод кода не нужен. В Mini App доступны данные аккаунта, услуги, настройка напоминаний и переписка с поддержкой. Открытый экран поддержки обновляется каждые 10 секунд.
