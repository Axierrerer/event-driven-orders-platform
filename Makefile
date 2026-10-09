SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
SERVICES := auth-service user-service product-service inventory-service order-service notification-service api-gateway
PACKAGES := libs/events libs/platform $(SERVICES)
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help doctor install lint format typecheck test test-integration dev-up dev-down dev-reset dev-logs dev-ps export-schemas check-schemas register-schemas compat-schemas proto obs-up obs-down check-alerts seed e2e load scan k3d-up k3d-down inject-secrets helm-check k3d-zero-downtime

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
	uv run python scripts/seed.py
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

obs-up: ## Стенд + observability: Jaeger, Prometheus, Grafana, Loki (нужно ~2 GB RAM сверху)
	OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 $(COMPOSE) --profile observability up -d --build --wait
	@echo ""
	@echo "  Grafana:    http://localhost:3000 (дашборды в папке Orders Platform)"
	@echo "  Jaeger:     http://localhost:16686"
	@echo "  Prometheus: http://localhost:9090 (алерты: /alerts)"

obs-down: ## Остановить стенд вместе с observability
	$(COMPOSE) --profile observability down

check-alerts: ## Проверить правила алертов Prometheus и их unit-тесты (promtool)
	docker run --rm -v "$(CURDIR)/observability/prometheus:/rules:ro" -w /rules \
		--entrypoint promtool prom/prometheus:v3.2.1 check rules alerts.yml
	docker run --rm -v "$(CURDIR)/observability/prometheus:/rules:ro" -w /rules \
		--entrypoint promtool prom/prometheus:v3.2.1 test rules alerts_test.yml

seed: ## Тестовые данные стенда: админ, менеджер, категории, товары, остатки (идемпотентно)
	uv run python scripts/seed.py

E2E_RESERVATION_TTL ?= 15

# На время e2e: короткий срок резерва и высокие лимиты gateway (тесты часто входят в систему)
E2E_ENV := RESERVATION_TTL_SECONDS=$(E2E_RESERVATION_TTL) GATEWAY_LOGIN_RATE_CAPACITY=100000 \
	GATEWAY_ANONYMOUS_RATE_CAPACITY=100000 GATEWAY_USER_RATE_CAPACITY=100000

e2e: ## Сквозные сценарии против стенда (срок резерва и лимиты меняются на время прогона)
	$(E2E_ENV) $(COMPOSE) up -d --wait inventory-service inventory-worker api-gateway nginx
	@status=0; (cd e2e && uv run pytest -q) || status=$$?; \
		$(COMPOSE) up -d --wait inventory-service inventory-worker api-gateway nginx >/dev/null 2>&1; \
		exit $$status

LOAD_USERS ?= 100
LOAD_DURATION ?= 60s

load: ## Нагрузочный тест (locust, ~500 RPS) через Nginx; отчёт — docs/perf/report.md
	GATEWAY_ANONYMOUS_RATE_CAPACITY=1000000 GATEWAY_USER_RATE_CAPACITY=1000000 \
		$(COMPOSE) up -d --wait api-gateway nginx
	@mkdir -p load/reports
	@status=0; uv run locust -f load/locustfile.py --headless --host http://localhost:$${GATEWAY_HOST_PORT:-8000} \
		-u $(LOAD_USERS) -r 20 -t $(LOAD_DURATION) --csv load/reports/run --only-summary || status=$$?; \
		$(COMPOSE) up -d --wait api-gateway nginx >/dev/null 2>&1; \
		uv run python scripts/perf_report.py load/reports/run_stats.csv docs/perf/report.md; \
		exit $$status

scan: ## Безопасность: pip-audit, gitleaks, trivy (конфиги и образы)
	./scripts/scan.sh

# ---------------- Kubernetes (k3d + Helm) ----------------
k3d-up: ## Кластер k3d со всей платформой (https://api.orders.localhost)
	./scripts/k3d-up.sh

k3d-down: ## Удалить кластер k3d и его registry
	k3d cluster delete orders
	-k3d registry delete k3d-registry.localhost

inject-secrets: ## Локальные секреты → SealedSecret в кластере
	./scripts/inject-secrets.sh

helm-check: ## helm lint и kubeconform для всех чартов
	./scripts/helm-check.sh

k3d-zero-downtime: ## Под нагрузкой: scale order-service ×4 и helm upgrade — без 5xx
	./scripts/k8s-zero-downtime.sh
