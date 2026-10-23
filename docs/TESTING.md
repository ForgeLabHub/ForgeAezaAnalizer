# Тестирование

## Запуск

```bash
python -m pytest tests/ -q          # весь набор
python -m pytest tests/ -v          # подробно
python -m pytest tests/test_risk_model.py -v
```

## Набор тестов

| Файл | Что покрывает | Тестов |
|---|---|---:|
| `test_archive.py` | безопасность распаковки: traversal, absolute, дубликаты, symlink, ratio, nested, повреждённый | 7 |
| `test_money.py` | правило 100:1, отсутствие float-дрейфа, `None` остаётся `None` | 3 |
| `test_validation.py` (в `test_importer.py`) | типы, диапазоны, даты, ссылочная целостность | — |
| `test_importer.py` | реальный датасет, идемпотентность, атомарность, откат, наивные даты | 8 |
| `test_risk_model.py` | формула, нормализация, неизвестные, границы полос, валидация весов | 9 |
| `test_revenue.py` | eligible-продления, исключения, отсутствие двойного счёта | 5 |
| `test_api.py` | эндпоинты, фильтры, сортировки, ошибки, идемпотентность | 16 |
| `test_robustness.py` | повреждённая БД, пустой датасет, клиент без услуг | 4 |

Итого: **52 теста**.

## Что проверяется (инварианты)

| Инвариант | Где |
|---|---|
| Импорт даёт 10/30/100 без отклонений | `test_imports_real_dataset` |
| Повторный импорт не создаёт дубликатов | `test_reimport_is_idempotent` |
| Ошибочный импорт не меняет данные | `test_failed_import_leaves_previous_data_intact` |
| Path traversal отклоняется | `test_rejects_path_traversal` |
| Неизвестное ≠ нулевой риск | `test_unknown_balance_is_excluded_not_zeroed` |
| Полосы без дыр (34.9 → low) | `test_band_boundaries_are_inclusive` |
| `deleted` = уже отток | `test_deleted_service_excluded_from_revenue` |
| Баланс не входит в выручку | `test_balance_is_not_part_of_revenue_at_risk` |
| Изменение весов меняет результат | `test_weight_change_alters_scores` |
| Повреждённая БД → понятная ошибка | `test_corrupt_store_raises_clear_error` |

## Регрессии, добавленные при исправлении дефектов

| Дефект | Тест |
|---|---|
| Дыра в полосах риска (34.9 → `high`) | `test_band_boundaries_are_inclusive` |
| Наивные даты из SQLite ломали сравнения | `test_naive_timestamp_is_rejected`, `UTCDateTime` |
| Перекрытие переменной `service` → 500 | `test_customer_detail_has_services_and_reasons` |
| `Settings` не подхватывал env при тестах | все тесты через фикстуру `data_dir` |
| Повреждённая БД → сырой traceback | `test_corrupt_store_raises_clear_error` |
| Пустой датасет / клиент без услуг | `test_empty_dataset_is_handled`, `test_account_without_services_is_unknown_not_low` |

## Ручные проверки (проведены)

| Проверка | Процедура | Результат |
|---|---|---|
| Импорт | `python -m aeza_analyzer.cli import` | 10/30/100, rejected 0 |
| Профиль | `python -m aeza_analyzer.cli audit` | полный JSON-профиль |
| Запуск скрипта | `bash /path/run.sh --port 8099` из `/tmp` | venv + импорт + сервер, HTTP 200 |
| Повторный запуск | повторный `run.sh` | «existing store found», хеш БД не изменился |
| Остановка | `kill -INT` серверу | 0 оставшихся процессов |
| Конфликт порта | `run.sh --port <занятый>` | сообщение + exit 1 |
| Отсутствие архива | `AEZA_SOURCE_ZIP=/nope run.sh` | сообщение + exit 1 |
| API | `curl` по всем эндпоинтам | 200 (см. отчёт) |
| UI | Playwright: dashboard, клиенты, поиск, карточка, модель, данные, повторный импорт | без ошибок в консоли |
| Веса | `PUT /api/weights` → dashboard | €7.48 → €6.93 → сброс → €7.48 |

## Ограничения тестирования

- Браузерная проверка выполнена Playwright'ом по локальному серверу; внешние
  браузеры и мобильные устройства не проверялись.
- Тесты используют SQLite; поведение на PostgreSQL не проверялось.
- Аутентификация отсутствует, поэтому проверки прав доступа нет.
