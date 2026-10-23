# Разработка

## Окружение

- Python **3.10+** (проверено на 3.13)
- Зависимости: `requirements.txt`
- Внешние сервисы не требуются

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`run.sh` делает это автоматически.

## Структура кода

```
aeza_analyzer/
  config.py            env-пути (ленивые свойства)
  money.py             евроценты → евро
  models.py            ORM-модели + UTCDateTime
  db.py                engine/session, check_store(), StoreError
  audit.py             профиль данных
  cli.py               import / audit / serve
  importer/
    archive.py         безопасная распаковка
    validation.py      валидация записей
    loader.py          атомарная загрузка
  analytics/
    risk.py            факторы и скоринг
    service.py         агрегация, выручка, dashboard
  api/
    app.py             эндпоинты
    schemas.py         Pydantic-схемы
  static/              SPA
tests/                 pytest
```

## Соглашения

- **Деньги — только целые евроценты** внутри; евро на границе API.
- **Неизвестное ≠ 0**: отсутствующие данные дают `None`, не `0`.
- **Импорт атомарен**: одна транзакция, никаких частичных записей.
- **Слои не пересекаются**: аналитика не знает про HTTP.
- Типизация: аннотации типов на публичных функциях, `from __future__ import annotations`.
- Комментарии — только там, где код неочевиден (инвариант, обход, компромисс).

## Частые ошибки

| Ошибка | Последствие | Как избежать |
|---|---|---|
| `from .config import settings` + reload | замороженные пути | `Settings` читает env лениво |
| локальная переменная `service` в API | перекрывает сервис аналитики → 500 | не называть переменные `service` в обработчиках |
| деление на `Σw` без проверки | `ZeroDivisionError` | `known_weight <= 0` → `unknown` |
| сравнение naive/aware datetime | `TypeError` | всегда `UTCDateTime` |
| конвертация `amount` в евро | смешение семантик | `amount` — не деньги |

## Миграции

Схема создаётся автоматически (`Base.metadata.create_all`). Отдельных
миграций нет: проект использует один источник данных и пересоздаваемое
хранилище. При смене схемы — удалить `data/aeza.sqlite` и переимпортировать.

## Добавление фактора риска

1. Добавить ключ и вес в `DEFAULT_WEIGHTS` (`analytics/risk.py`).
2. Написать функцию-фактор, возвращающую `Factor`.
3. Добавить её в список `raw` в `score_service`.
4. Добавить заголовок в `FACTOR_TITLES`.
5. Добавить тест в `tests/test_risk_model.py`.

## Полезные команды

```bash
python -m aeza_analyzer.cli import          # импорт
python -m aeza_analyzer.cli import --lenient  # импорт, пропуская плохие строки
python -m aeza_analyzer.cli audit           # профиль данных
python -m aeza_analyzer.cli serve --port 9000
python -m pytest tests/ -q                  # тесты
python -m pytest tests/test_risk_model.py -v
```

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `AEZA_DATA_DIR` | `<root>/data` | каталог хранилища |
| `AEZA_SOURCE_ZIP` | `<root>/датасет.zip` | исходный архив |
| `AEZA_DATABASE_URL` | `sqlite+pysqlite:///<data>/aeza.sqlite` | переопределение хранилища |
| `AEZA_HOST` / `AEZA_PORT` | `127.0.0.1` / `8000` | параметры `run.sh` |
| `AEZA_VENV_DIR` | `<root>/.venv` | каталог venv для `run.sh` |

Секретов проект не требует.
