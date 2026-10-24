# API

Базовый префикс: `/api/v1`. Интерактивная схема текущей сборки доступна по `/api/v1/docs`, JSON OpenAPI — по `/api/v1/openapi.json`. Список в этой справке сгруппирован; OpenAPI является точным источником параметров и схем ответов.

## Доступ

`/health`, `/ready`, `/api/v1/docs` и `/api/v1/openapi.json` доступны без токена. Вход выполняется через `POST /api/v1/auth/login`; приватные маршруты принимают `Authorization: Bearer <token>`. `/metrics` принимает отдельный Bearer-токен из `AEZA_METRICS_TOKEN`, если он задан, иначе требует сессию аналитика.

## Маршруты

| Группа | Маршруты | Назначение |
| --- | --- | --- |
| Auth | `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` | Вход, профиль, выход |
| Аналитика | `GET /api/v1/analytics/summary`, `GET /api/v1/analytics/events` | Сводка и поток обновлений опубликованного расчёта |
| Клиенты | `GET /api/v1/customers`, `GET /api/v1/customers/{customer_id}` | Фильтрация, сортировка, страницы и карточка клиента |
| Рекомендации | `GET /api/v1/customers/{customer_id}/recommendations`, `PATCH /api/v1/customers/{customer_id}/recommendations/{code}` | Состояние playbook-рекомендации |
| Приоритеты и сценарии | `GET /api/v1/priority`, `POST /api/v1/scenarios/compare`, `GET /api/v1/quality` | Очередь работы, what-if сравнение и качество данных |
| Настройки модели | `GET /api/v1/model/settings`, `PATCH /api/v1/model/settings`, `POST /api/v1/model/settings/reset` | Чтение и изменение параметров расчёта |
| Источник | `GET /api/v1/source/snapshot`, `PUT /api/v1/source/snapshot`, `GET /api/v1/source/observations` | Чтение и атомарная замена снимка, наблюдения статусов |
| Действия | `GET /api/v1/actions`, `POST /api/v1/actions`, `PATCH /api/v1/actions/{action_id}` | Запись и сопровождение подтверждённых действий по удержанию |
| Экспорт | `GET /api/v1/export/customers.csv` | Потоковый экспорт текущей отфильтрованной выборки |
| AI Analyst | `/api/v1/ai/status`, `/api/v1/ai/chat`, `/api/v1/ai/customers/{customer_id}/explain`, `/api/v1/ai/scenarios/explain`, `/api/v1/ai/reports/summary` | Необязательные объяснения и сводки |
| Агрегатный AI | `POST /api/v1/insights/ai` | Ответ по агрегатам расчёта через отдельную AI-поверхность |

## Версии данных

Результат связан с generation источника и модели. Если API возвращает `X-Analysis-Generation`, используйте эту версию при навигации по связанным страницам. CSV экспорт сообщает размер отфильтрованной выборки в `X-Export-Rows` и закрепляет все страницы за generation первого запроса.

## Ошибки

Основные ответы: `401` — нет действующей авторизации, `404` — ресурс не найден, `409` — конфликт версии/состояния, `422` — некорректный запрос или снимок, `502` — нарушен контракт подключённого модуля, `503` — расчёт или необязательный AI-модуль недоступен. Формат конкретного ответа описан в OpenAPI.

Локальный OpenAPI может содержать playbooks и другие новые маршруты, которых ещё нет на production stand. Проверяйте спецификацию именно того окружения, к которому подключается клиент.
