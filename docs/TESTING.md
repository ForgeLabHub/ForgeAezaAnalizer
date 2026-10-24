# Проверки

## Наборы тестов

Числа получены фактическим запуском на текущем коде (проверено 2026-10-24):

| Компонент | Команда | Результат |
|---|---|---|
| B: основной продукт | `cd backend && python -m pytest tests/ -q` | **246 passed** |
| C: auth-модуль | `python -m pytest tests/test_auth.py -q` (из корня) | **17 passed** |
| A: анализатор | `python -m pytest tests/ -q --ignore=tests/test_auth.py` (из корня) | **52 passed** |
| Всё вместе (корень: A + C) | `python -m pytest tests/ -q` | **69 passed** |

Итого: **246** тестов части B и **69** тестов корневого набора (52 части A + 17
части C), все проходят.

Состав тестов меняется, поэтому числа выше — это результат конкретного запуска,
а не постоянная величина. При отчёте указывайте результат фактического запуска.
Предыдущие редакции этого документа указывали 108/177 — это устаревшие значения.

## Сборка фронтенда

```bash
cd frontend && npm ci && npm run build
```

Результат проверенного запуска:

```
dist/index.html                   0.97 kB │ gzip:  0.59 kB
dist/assets/index-*.css          30.43 kB │ gzip:  6.92 kB
dist/assets/index-*.js          264.74 kB │ gzip: 83.28 kB
✓ 50 modules transformed, built in 1.03s
```

Проверка ссылок, переменных `AEZA_*`, задокументированных API-путей и потенциальных секретов:

```bash
python backend/scripts/check_docs.py
```

## Локальный запуск для проверки

```bash
# из корня репозитория
export AEZA_JWT_SECRET=... AEZA_ADMIN_EMAIL=analyst@aeza.test \
       AEZA_ADMIN_PASSWORD=... AEZA_SEED_DEMO_DATA=1 \
       AEZA_SNAPSHOT_PATH=backend/data/snapshot.json \
       AEZA_ANALYTICS_FACTORY=backend.app.domain.module:create
python -m uvicorn main:app --host 127.0.0.1 --port 8210
```

## Перед запуском

- Запускайте команды из корня репозитория, если команда не требует `cd frontend`.
- Проверьте `AEZA_*` в окружении. Унаследованные значения могут изменить конфигурацию API и дать неожиданные ошибки.
- Для интеграционной проверки поднимите стек через Compose и используйте актуальную OpenAPI-схему приложения.
- Не запускайте длительные нагрузочные тесты Docker-стека без необходимости; для профилей используйте скрипты `backend/scripts/` с малым объёмом и ограниченной длительностью.

Frontend-тестовый runner в `frontend/package.json` не настроен; typecheck и production build не заменяют браузерную проверку пользовательских сценариев.
