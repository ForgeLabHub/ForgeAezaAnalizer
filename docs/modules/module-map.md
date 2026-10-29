# Карта модулей: что заимствовать в другой проект

Таблица отвечает на вопрос «что взять, если нужно X»: минимальный набор файлов,
зависимости и что придётся заменить.

| Нужно | Взять файлы | Внешние зависимости | Заменить |
| --- | --- | --- | --- |
| Расчёт риска и выручки без I/O | `backend/app/domain/` (`risk.py`, `revenue.py`, `money.py`, `provenance.py`) | — | набор факторов и правила |
| Деньги без float | `backend/app/domain/money.py` | — | валюту и точность |
| Провенанс цифр | `backend/app/domain/provenance.py` | — | формат ссылки на источник |
| Применение схемы и миграции | `backend/app/schema.py` | SQLAlchemy | реестр миграций под свой проект |
| Аутентификация на JWT в отдельной базе | `backend/auth/`, `backend/auth_schema.sql` | `PyJWT[crypto]` | таблицы и роли |
| Слой инструментов для LLM | `backend/app/ai/tools/` | `httpx` | сами инструменты |
| Провайдер LLM с mock-реализацией | `backend/app/ai/providers/` | `httpx` | вызов и парсинг ответа |
| Метрики Prometheus по маршрутам | `backend/app/metrics.py` | `prometheus_client` | список метрик |
| Приём снимка по токену | `backend/app/api/routes_source.py` | FastAPI | формат снимка |
| Адаптеры внешних каналов | `backend/app/integrations/`, `backend/app/telegram/` | SMTP, Telegram API | провайдеры |

## Правила переноса

1. Домен не знает про HTTP, БД и сеть — его можно забрать целиком и протестировать
   без контейнеров.
2. Адаптеры (`providers`, `integrations`) прячут внешнюю систему за интерфейсом:
   заменяется реализация, а не вызывающий код.
3. Тесты — часть модуля: домен → `backend/tests/test_domain.py`, auth →
   `tests/test_auth.py`, AI → `backend/tests/test_ai.py`.
4. Конфигурация — только через `backend/app/config.py` (`Settings`), значения по
   умолчанию безопасные.

## Чего здесь нет

- Нет ORM-моделей домена: данные читаются из снимка, а не из таблиц по одной записи.
- Нет очереди задач: фоновые пересчёты живут в процессе.
