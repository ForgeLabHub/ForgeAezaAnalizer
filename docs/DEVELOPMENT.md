# Разработка

Основной локальный сценарий — полный стек через Docker Compose. Он поднимает PostgreSQL, FastAPI API и frontend на портах `8000` и `8080`.

## Требования

- Docker с поддержкой Compose
- Python 3.12 для запуска тестов и вспомогательных скриптов
- Node.js и npm для разработки frontend вне контейнера

## Запуск приложения

Из корня репозитория:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Перед запуском задайте в `.env` собственные `AEZA_JWT_SECRET` и `AEZA_ADMIN_PASSWORD`; для локального UI укажите `AEZA_CORS_ORIGINS=http://localhost:8080`. Полный список настроек и значения Compose описаны в [развёртывании](DEPLOYMENT.md).

## Проверки

```powershell
python -m pytest backend/tests/ -q
python -m pytest tests/ -q
python backend/scripts/check_docs.py
```

Frontend:

```powershell
cd frontend
npm ci
npm run build
```

При ручном запуске API нужен PostgreSQL и полный набор настроек из `.env.example`: сам Python-процесс не загружает `.env`. Для обычной проверки интеграции используйте Compose.

## Структура

- `backend/app/domain/` — правила расчёта и предметная логика.
- `backend/app/api/` — HTTP-маршруты и сериализация.
- `backend/app/ai/` — дополнительные AI-интерфейсы, выключены по умолчанию.
- `frontend/src/` — React + TypeScript SPA.
- `backend/tests/`, `tests/` — тесты backend-приложения и корневых компонентов.
- `backend/scripts/` — утилиты загрузки снимка, проверки документации и ограниченного нагрузочного тестирования.

## Практические правила

- Храните денежные значения во внутренних расчётах в целых евроцентах.
- Сохраняйте различие между состоянием услуги, завершёнными событиями и прогнозным риском.
- Не описывайте score как вероятность или точность модели.
- Не добавляйте локальные базы, секреты и результаты сборки в Git.
- Перед тестами проверьте переменные `AEZA_*` в текущем shell: неожиданные значения меняют настройки тестового приложения.

Сверяйте документацию и маршруты командой `python backend/scripts/check_docs.py`.
