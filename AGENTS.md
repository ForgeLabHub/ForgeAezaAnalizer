# AGENTS.md — Aéza Analyzer

Пиши лаконичный код без лишних комментариев. При добавлении новой технологии
или библиотеки явно указывай на это. Не выходи за рамки запроса.

## Проект

Поддерживаемое приложение состоит из FastAPI (`backend/app/`), React + TypeScript
(`frontend/`) и PostgreSQL. Авторизация вынесена в общий модуль `backend/auth/`;
учётные записи и серверные сессии хранятся в отдельной SQLite. Полный стек
запускается через корневой `docker-compose.yml` и `run.sh`.

## Структура

```text
backend/app/       API, доменная логика и хранение
backend/auth/      пароли, сессии, RS256 и OIDC
backend/tests/     тесты API и доменной логики
frontend/src/      React + TypeScript SPA
dataset/           официальный снимок и генератор набора
docs/              актуальная справка и материалы презентации
scripts/           резервное копирование и восстановление
```

## Команды

```bash
cp .env.example .env       # задайте POSTGRES_PASSWORD
./run.sh                   # docker compose up --build -d
docker compose exec api python -m backend.users create analyst@example.com
python -m pytest backend/tests/ -q
python -m pytest tests/test_auth.py -q
cd frontend && npm ci && npx tsc -b && npm run build
```

В `.env` не храните демонстрационный пароль на общем или публичном стенде.
Compose намеренно не запускается без `POSTGRES_PASSWORD`.

## Неподвижные условия

- Внутренние денежные значения — целые евроценты. `transactions.amount` не является денежным полем.
- Риск — объяснимая взвешенная оценка, не вероятность оттока. Цена услуги не входит в риск.
- Оценка клиента — максимум по прогнозируемым услугам. `deleted` и `blocked` — завершённые состояния.
- Отсутствующий фактор исключается из взвешенного среднего и снижает confidence; неизвестное не равно нулю.
- Выручка под риском учитывает по одному будущему продлению открытой платной услуги в заданном горизонте.
- `AEZA_AS_OF` по умолчанию закреплён на `2026-10-19T15:00:00+00:00`; меняйте его намеренно.
- Импорт снимка атомарный: отклонённый набор не должен менять опубликованные данные.
- `Core.update(force=False)` не публикует новую generation без изменения данных или настроек.
- Экспорт клиентов остаётся потоковым и закреплённым за generation первой страницы.
- `/metrics` принимает ограниченную по пути HttpOnly-cookie, Bearer access token или `AEZA_METRICS_TOKEN`.

## Эксплуатация

`scripts/backup.sh` и `scripts/restore.sh` — поддерживаемый путь резервирования.
Восстановление требует `--yes`; SQLite копируется через online-backup API.
Резервные копии содержат реальные учётные данные и остаются вне Git.

AI Analyst использует документацию из `docs/`; Dockerfile копирует её в образ и
собирает RAG-индекс при сборке. Не переносите документы или индекс без обновления
пути и сборки образа.

Публичный стенд: `https://aeza-sentinel.pixel-minds.ru/`. Проверяйте его OpenAPI
и фактические настройки отдельно: локальные изменения сами по себе не означают
обновление стенда.

## Telegram-бот (клиентский) — 2026-10-24

Клиентская интеграция: привязка Telegram к аккаунту по email-OTP, Mini App и
поддержка. Выключена по умолчанию (`AEZA_TELEGRAM_BOT_ENABLED=0`). Runbook —
`docs/TELEGRAM_BOT.md`, спецификация — `TELEGRAM_BOT_PLAN.md`.

Неочевидные инварианты:

- **Webhook всегда отвечает 200**, кроме неверного секрета (403) и выключенного
  бота (503). 5xx заставил бы Telegram бесконечно повторять один и тот же update.
  Поэтому ошибка отправки ответа (`_send_text`) не пробрасывается наружу.
- **Дедупликация по `update_id`** (`analyzer_telegram_updates`, PK) — вставка
  коммитится до бизнес-действия; повторный `/start` не перепривязывает чат.
  Плюс `SupportMessageRow.telegram_message_id` уникален.
- **OTP-потребление — compare-and-set**: `UPDATE ... WHERE consumed_at IS NULL`
  и проверка `rowcount == 1`, потому что `with_for_update` в SQLite не работает.
- **Провайдер Telegram вырезает токен** из всех ошибок и не чейнит исходный
  `HTTPError` (в его `.url` есть токен), иначе он попал бы в traceback и логи.
- **Регистрация webhook — явная** (`POST /telegram/webhook/register`), не при
  старте: иначе рестарт гоняет с другими инстансами. Требуется публичный HTTPS.
- **OTP-почта заблокирована** до согласования контракта: `UnconfiguredEmailProvider`
  бросает, письмо не подменяется фиктивным успехом. Seam — `EmailProvider.send_otp`.
- **Mini App** (`frontend/src/pages/MiniAppPage.tsx`, `/mini-app`) рендерится до
  гейта аналитика и использует отдельный клиентский токен (`clientRequest`), не
  сессию аналитика.
- Клиенту не показываются risk score, причины риска и рекомендации — по плану.

## Публикация в main и deploy (2026-10-24)

**Опубликовано:** `main` = `3bddd25` (проверено через GitHub API и `ls-remote`).
Токен: classic PAT с полным `repo` (передаётся per-command, в конфиг не пишется).
Токены из окружения агента (`GITHUB_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`) —
read-only (403).

**Deploy на стенд — ЗАБЛОКИРОВАН.** Стенд `aeza-sentinel.pixel-minds.ru`
резолвится в `158.160.212.225` (не в старый `84.201.150.227`). SSH (порт 22)
принимает **только publickey**; приватного ключа в окружении агента нет, а
учётные данные владельца — это логины аккаунтов (GitHub/почта), не SSH-ключи.
Автоматического пути тоже нет: в репозитории нет `render.yaml`/deploy-скрипта,
у репозитория нет webhooks, в GitHub Actions нет secrets.

Что нужно от владельца: добавить публичный ключ агента в
`~/.ssh/authorized_keys` на сервере (или выдать deploy-ключ), затем
`git pull` в каталоге проекта + `docker compose up -d --build`.

Проверка, какая версия развёрнута (404 = ещё старая):
`curl -s -o /dev/null -w '%{http_code}' https://aeza-sentinel.pixel-minds.ru/api/v1/email/status`

## Почта: Postbox + SMTP.BZ (2026-10-24)

Исходящая почта идёт через один провайдер, выбранный `AEZA_EMAIL_PROVIDER`
(пусто = авто: Postbox, иначе SMTP.BZ). Оба транспорта живут в
`backend/app/integrations/email.py` за одним контрактом `send_email`; отдельная
система не создавалась, Telegram-OTP сохраняет интерфейс `EmailProvider`.

- Postbox: SMTP `postbox.cloud.yandex.net`, 465 (TLS) или 587 (STARTTLS),
  `AUTH PLAIN/LOGIN` с идентификатором и секретом API-ключа. Подтверждение —
  `250` на `DATA`; отказ на `MAIL FROM` → `EmailRejected`.
- Явно выбранный провайдер без учётных данных **выключает** почту, а не
  переключается молча: подтверждение может прийти только от реально
  использованного провайдера.
- Секреты — только из окружения; статус и ошибки их не печатают.
- Тесты: `backend/tests/test_postbox.py` поднимает локальный SMTP-сервер
  (`aiosmtpd`, dev-зависимость) и проверяет приём, отказ отправителя, отказ
  аутентификации, недоступный сервер, STARTTLS и обвязку роутов.

**Push и deploy — ЗАБЛОКИРОВАНЫ.** Оба токена окружения (`GITHUB_TOKEN`,
`GITHUB_PERSONAL_ACCESS_TOKEN`) и GitHub-MCP read-only: `POST /git/refs` →
`403 Resource not accessible by personal access token`. Изменения закоммичены
локально (`main`, поверх `58685d0`). SSH на стенд тоже недоступен (publickey
без ключа). Владельцу: запушить ветку с write-токеном, затем `git pull` +
`docker compose up -d --build` на сервере.

Внешние требования, которые не обходятся кодом: домен `pixel-minds.ru` должен
быть привязан к Postbox с Easy DKIM (две CNAME), адрес отправителя — из этого
домена, а API-ключ — с областью `yc.postbox.send`. Подробности в `docs/EMAIL.md`.
