SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
SERVICES := auth-service user-service product-service inventory-service order-service notification-service api-gateway
PACKAGES := libs/events libs/platform $(SERVICES)
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help doctor install lint format typecheck test test-integration dev-up dev-down dev-reset dev-logs dev-ps export-schemas check-schemas register-schemas compat-schemas proto

help: ## Список целей
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

doctor: ## Проверить окружение разработчика
	@./scripts/doctor.sh

install: ## Установить зависимости всего workspace
	uv sync --all-packages

lint: ## ruff check + проверка формата + правила слоёв + актуальность схем событий
	uv run ruff check .
	uv run ruff format --check .
	uv run python -m events.schemas_cli check
	@tmp=$$(mktemp -d) && ./scripts/generate-proto.sh "$$tmp" && \
		diff -r -x __pycache__ "$$tmp/orders_proto" libs/proto/src/orders_proto >/dev/null; \
		status=$$?; rm -r "$$tmp"; \
		if [ $$status -ne 0 ]; then echo "gRPC-код устарел: выполните make proto"; exit 1; fi
	@set -e; for s in $(SERVICES); do (cd $$s && uv run lint-imports --no-cache | tail -1 | sed "s|^|$$s: |"); done

format: ## Автоисправление и форматирование
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy по каждому пакету (корневой конфиг — pyproject.toml)
	@set -e; for p in $(PACKAGES); do echo "== $$p"; (cd $$p && uv run mypy --config-file $(CURDIR)/pyproject.toml src); done

test: ## Unit-тесты всех пакетов
	@set -e; for p in $(PACKAGES); do echo "== $$p"; (cd $$p && uv run pytest -q -m "not integration"); done

test-integration: ## Интеграционные тесты (testcontainers, нужен Docker)
	@set -e; for p in $(PACKAGES); do echo "== $$p"; (cd $$p && uv run pytest -q -m integration --no-cov) || [ $$? -eq 5 ]; done

dev-up: ## Поднять локальный стенд одной командой
	$(COMPOSE) up -d --build --wait
	@echo ""
	@echo "Стенд поднят:"
	@echo "  API gateway / Swagger: http://localhost:$${GATEWAY_HOST_PORT:-8000}/docs"
	@echo "  Mailpit:               http://localhost:$${MAILPIT_UI_HOST_PORT:-8025}"
	@echo "  Schema Registry:       http://localhost:$${SCHEMA_REGISTRY_HOST_PORT:-8081}"
	@echo "  Kafka (с хоста):       localhost:$${KAFKA_HOST_PORT:-9094}"

dev-down: ## Остановить стенд (данные сохраняются)
	$(COMPOSE) down

dev-reset: ## Остановить стенд и удалить тома
	$(COMPOSE) down -v

dev-logs: ## Логи стенда
	$(COMPOSE) logs -f --tail=100

dev-ps: ## Состояние контейнеров
	$(COMPOSE) ps

SCHEMA_REGISTRY_URL ?= http://localhost:$${SCHEMA_REGISTRY_HOST_PORT:-8081}

export-schemas: ## Перегенерировать JSON Schema событий в libs/events/schemas
	uv run python -m events.schemas_cli export

check-schemas: ## Проверить, что схемы в репозитории совпадают с моделями
	uv run python -m events.schemas_cli check

register-schemas: ## Зарегистрировать схемы в Schema Registry (идемпотентно)
	uv run python -m events.schemas_cli register --url $(SCHEMA_REGISTRY_URL)

compat-schemas: ## Проверить совместимость моделей со схемами в реестре
	uv run python -m events.schemas_cli compat --url $(SCHEMA_REGISTRY_URL)

proto: ## Сгенерировать Python-код gRPC из proto/ в libs/proto
	./scripts/generate-proto.sh
