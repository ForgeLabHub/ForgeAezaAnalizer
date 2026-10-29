# Aéza Analyzer — единая точка входа для сборки и проверок.
#
# Контракт: `make <target>` работает из чистого клона, не требует секретов,
# кроме явно интеграционных целей. Windows-разработчики используют `make` из
# Git Bash/WSL либо команды, указанные в BUILD.md.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

PYTHON          ?= python3
PYTHON_VERSION  := 3.12
NODE_VERSION    := 22
COMPOSE         ?= docker compose
API_URL         ?= http://localhost:8000

.PHONY: help doctor venv install build build-frontend test test-backend test-auth \
        test-frontend lint openapi openapi-check docs-check compose-up compose-down \
        compose-logs migrate smoke-test backup restore verify clean

help: ## Список целей
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

doctor: ## Проверить инструменты, версии и сервисы (ничего не меняет)
	@./scripts/doctor.sh

install: ## Установить зависимости backend и frontend
	$(PYTHON) -m pip install -r requirements-dev.txt
	cd frontend && npm ci --no-audit --no-fund

## --- Сборка ---------------------------------------------------------------

build: build-frontend ## Собрать артефакты (backend — Python-пакет, сборки нет)
	@$(PYTHON) -m compileall -q backend core.py main.py && echo "backend: компилируется"
	@echo "артефакт UI: frontend/dist"

build-frontend: ## Production-сборка React
	cd frontend && npm ci --no-audit --no-fund && npx tsc -b && npm run build

## --- Проверки -------------------------------------------------------------

test: test-backend test-auth ## Все unit-тесты
	@echo "test: ok"

test-backend: ## Основной набор
	$(PYTHON) -m pytest backend/tests -q

test-auth: ## Тесты модуля аутентификации
	$(PYTHON) -m pytest tests/test_auth.py -q

test-frontend: ## Typecheck и сборка UI (отдельных unit-тестов нет)
	cd frontend && npx tsc -b && npm run build

openapi: ## Перегенерировать backend/openapi.json
	$(PYTHON) backend/scripts/export_openapi.py

openapi-check: ## Проверить, что спецификация совпадает с приложением
	@$(PYTHON) backend/scripts/export_openapi.py --check

docs-check: ## Проверить документацию, ссылки и спецификации модулей
	@$(PYTHON) backend/scripts/check_docs.py
	@./scripts/docs-check.sh

## --- Интеграционная среда -------------------------------------------------

compose-up: ## Поднять стек
	$(COMPOSE) up --build -d

compose-down: ## Остановить (данные сохраняются)
	$(COMPOSE) down

compose-logs: ## Логи
	$(COMPOSE) logs -f --tail=200

create-user: ## Создать пользователя: make create-user EMAIL=... [PASSWORD=...]
	$(COMPOSE) exec api $(PYTHON) -m backend.users create $(EMAIL)

smoke-test: ## Проверить живой инстанс
	@./scripts/smoke-test.sh $(API_URL)

backup: ## Резервная копия БД и данных
	@./scripts/backup.sh

restore: ## Восстановление: make restore FILE=...
	@./scripts/restore.sh $(FILE)

verify: docs-check test openapi-check ## Полная локальная матрица
	@echo "verify: ok (compose-уровни проверяются в CI)"

clean: ## Удалить артефакты
	rm -rf frontend/dist frontend/node_modules/.vite
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
