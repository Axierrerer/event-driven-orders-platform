# Event-Driven Order Processing Platform

**English** | [Русский](README.ru.md)

An order processing platform for a small e-commerce shop: product catalog, users and roles,
checkout, inventory and notifications.

The system is a set of Python microservices (FastAPI, asyncio). Services talk to each other
asynchronously through Kafka and synchronously through REST and gRPC. An order goes from
checkout to delivery as a **choreography-based saga**: each service reacts to the events of
the others and publishes compensating events when something fails.

## Status

| Component | State |
|-----------|-------|
| Local stack (`make dev-up`), monorepo, linters, tests | ✅ done |
| `libs/events` — Kafka event contract | ✅ done |
| `libs/platform` — outbox, idempotent consumer, auth, logging | ✅ done |
| `auth-service` | ✅ done |
| `user-service` | ✅ done |
| `product-service` (REST + gRPC) | ✅ done |
| `inventory-service` (REST + gRPC) | ✅ done |
| `order-service` with the order saga | ✅ done |
| `notification-service` (emails, rate limiting) | ✅ done |
| `api-gateway` (routing, JWT, rate limiting, unified Swagger) behind Nginx | ✅ done |
| Observability: traces (OpenTelemetry → Jaeger), metrics (Prometheus), logs (Loki), Grafana dashboards, alerts | ✅ done |
| Seed data, end-to-end scenarios, load test | ✅ done |
| Kubernetes (k3d + Helm), security scans | ⏳ planned |

---

## Contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [Using the stack](#using-the-stack)
- [Development](#development)
- [Code conventions](#code-conventions)
- [Git workflow](#git-workflow)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```mermaid
flowchart LR
    client([Client]) -->|HTTP :8000| nginx[Nginx<br/>reverse proxy + LB]
    nginx -->|least_conn| gw[api-gateway × N]

    gw -->|REST| auth[auth-service]
    gw -->|REST| users[user-service]
    gw -->|REST / gRPC| product[product-service]
    gw -->|REST| inventory[inventory-service]
    gw -->|REST| orders[order-service]

    orders -->|gRPC: availability| inventory
    orders -->|gRPC: prices| product

    auth & users & product & inventory & orders <-->|events| kafka[(Kafka)]
    kafka --> notify[notification-service]
    notify -->|SMTP| mail[(Email)]
```

### Services

| Service | Responsibility | Storage | Protocols |
|---------|----------------|---------|-----------|
| `nginx` | Public entry point: reverse proxy and load balancer for the api-gateway replicas | — | HTTP |
| `api-gateway` | Routing, JWT check, rate limiting, unified Swagger; product cards over gRPC | Redis | REST, gRPC |
| `auth-service` | Registration, email verification, JWT access + refresh tokens | PostgreSQL | REST |
| `user-service` | User profiles and roles (`ROLE_USER`, `ROLE_MANAGER`, `ROLE_ADMIN`) | PostgreSQL | REST, Kafka |
| `product-service` | Catalog: CRUD, publishing, full-text search and filters | MongoDB, Redis | REST, gRPC, Kafka |
| `inventory-service` | Stock levels and reservations | PostgreSQL | gRPC, Kafka |
| `order-service` | Orders and their lifecycle | PostgreSQL | REST, gRPC, Kafka |
| `notification-service` | Order status emails, per-user rate limiting | MongoDB, Redis | Kafka |

Every service that publishes or consumes events runs as two containers from the same image:
the API (`<service>`) and a background worker (`<service>-worker`) that relays the outbox to
Kafka and consumes events.

### Order lifecycle

```mermaid
stateDiagram-v2
    [*] --> NEW: order placed
    NEW --> RESERVED: inventory.reserved
    NEW --> CANCELLED: inventory.reservation-failed
    RESERVED --> PAID: payment
    RESERVED --> CANCELLED: cancelled / reservation expired
    PAID --> SHIPPED: shipment
    PAID --> CANCELLED: cancelled with refund
    SHIPPED --> COMPLETED
    COMPLETED --> [*]
    CANCELLED --> [*]
```

### Kafka events

| Topic | Key | Producer | Consumers |
|-------|-----|----------|-----------|
| `user.created` | user_id | auth-service | user-service, notification-service |
| `user.verification-requested` | user_id | auth-service | notification-service |
| `user.roles-changed` | user_id | user-service | auth-service |
| `product.changed` | product_id | product-service | inventory-service |
| `order.created` | order_id | order-service | inventory-service, notification-service |
| `inventory.reserved` | order_id | inventory-service | order-service |
| `inventory.reservation-failed` | order_id | inventory-service | order-service |
| `inventory.released` | order_id | inventory-service | order-service |
| `order.status-changed` | order_id | order-service | inventory-service, notification-service |

Each topic has a dead-letter topic `<topic>.dlq` for messages that could not be processed
after retries. Event schemas are Pydantic models in `libs/events`; JSON Schemas generated
from them are committed under `libs/events/schemas` and registered in Schema Registry with
`BACKWARD` compatibility.

---

## Tech stack

| Area | Technologies |
|------|--------------|
| Language and web | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| Databases | PostgreSQL 16 (SQLAlchemy 2 async + asyncpg, Alembic), MongoDB 7 (Motor), Redis 7 (redis.asyncio) |
| Messaging | Apache Kafka (KRaft), Confluent Schema Registry (JSON Schema), confluent-kafka |
| Sync calls | REST (httpx), gRPC (grpcio) |
| Auth | JWT RS256 + JWKS (PyJWT), Argon2id (pwdlib) |
| Dependencies | uv (workspace, single `uv.lock`) |
| Quality | ruff (lint + format), mypy (strict), import-linter, pytest + pytest-asyncio, pytest-cov, testcontainers |
| Infrastructure | Docker, docker-compose, Nginx; Kubernetes (k3d) and Helm are planned |
| Observability | OpenTelemetry, Jaeger, Prometheus, Grafana, Loki, Grafana Alloy |
| Local mail | Mailpit |

---

## Repository layout

```
.
├── pyproject.toml              # uv workspace root + ruff and mypy settings
├── uv.lock                     # single lock file
├── Makefile                    # all project commands (make help)
├── docker-compose.yml          # local stack
├── nginx/nginx.conf            # public entry point: reverse proxy + load balancer
├── observability/             # Collector, Prometheus (+ alerts), Loki/Alloy, Grafana
├── proto/                      # .proto sources of internal gRPC APIs
├── scripts/                    # all scripts
│   ├── doctor.sh               #   developer environment check
│   ├── generate-proto.sh       #   Python code generation from proto/
│   ├── postgres-init-databases.sh  # databases and roles of the services
│   └── kafka-create-topics.sh  #   topics and their DLQs
├── libs/
│   ├── events/                 # Kafka event contract (Pydantic models + JSON Schemas)
│   ├── platform/               # outbox, consumer, JWT, logging, health, locks, workers
│   └── proto/                  # generated gRPC code (package orders_proto)
└── <service>/                  # auth-service, user-service, product-service, ...
    ├── pyproject.toml
    ├── Dockerfile
    ├── alembic.ini, migrations/   # PostgreSQL services
    ├── src/
    │   ├── main.py             # FastAPI application factory
    │   ├── worker.py           # background process: outbox relay + Kafka consumer
    │   ├── config.py           # settings from environment variables
    │   ├── api/                # HTTP only: routes, request/response schemas
    │   ├── services/           # use cases, transactions
    │   ├── domain/             # pure models and rules, no I/O
    │   └── repositories/       # database access
    └── tests/
        ├── unit/
        └── integration/
```

Service code lives directly in `<service>/src/` and is imported as `src.*`. Each service is a
virtual member of the uv workspace: uv installs its dependencies, but the service itself is not
installed as a package. The libraries in `libs/` are installed as the packages `events`,
`platform_lib` and `orders_proto`.

---

## Quick start

### 1. Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python and dependencies |
| Docker Desktop / OrbStack / Colima | Engine ≥ 25, Compose v2 | local stack, testcontainers |
| GNU Make | ≥ 3.81 | project commands |
| git | ≥ 2.40 | — |
| k3d, kubectl, helm, kubeseal, trivy, grpcurl | recent | Kubernetes and scans (later stages) |

**macOS:**

```bash
xcode-select --install                                   # make, git
brew install uv k3d kubectl helm kubeseal trivy grpcurl
brew install --cask docker                               # or: brew install orbstack
uv python install 3.12
```

**Linux / Windows (WSL2):** install Docker, then:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
```

The stack needs about 1 GB of RAM; 2 CPUs and 8 GB of RAM are enough for development.

### 2. Install

```bash
git clone https://github.com/Axierrerer/event-driven-orders-platform.git
cd event-driven-orders-platform

make doctor     # checks that all tools are installed and Docker is running
make install    # uv sync --all-packages: all services and libraries in one .venv
```

### 3. Start the stack

```bash
make dev-up
```

One command builds the images, starts the infrastructure, creates databases, Kafka topics and
event schemas, runs migrations, starts all services and workers, two api-gateway replicas and
Nginx in front of them, and waits until everything is healthy. It takes about 30 seconds
(longer on the first run while images are downloaded).

No `.env` file is needed: every variable in `docker-compose.yml` has a local default. To
override something, e.g. a port that is already taken, create `.env` in the repository root:

```dotenv
GATEWAY_HOST_PORT=8080      # Nginx port on the host
GATEWAY_REPLICAS=3          # number of api-gateway replicas behind Nginx
POSTGRES_HOST_PORT=15432
```

`.env` is ignored by git.

### 4. Create the first administrator

Users with `ROLE_ADMIN` are not created through the public API. The user whose email matches
`BOOTSTRAP_ADMIN_EMAIL` (default `admin@example.com`) gets the admin role automatically:

```bash
docker compose exec -e NEW_USER_PASSWORD='choose a long passphrase' \
  auth-service python -m src.cli create-user --email admin@example.com --verified
```

The password is read from the environment, not from arguments, so it does not end up in the
process list. A few seconds later the role arrives through Kafka (`user.created` →
user-service → `user.roles-changed` → auth-service) and the next login token contains
`ROLE_ADMIN`.

### 5. Stop

```bash
make dev-down     # stop, data in volumes is kept
make dev-reset    # stop and delete all data
```

---

## Using the stack

### Addresses

| What | Address |
|------|---------|
| **API (Nginx → api-gateway)** | http://localhost:8000 |
| **Swagger for the whole platform** | http://localhost:8000/docs |
| Mailpit (emails) | http://localhost:8025 |
| Schema Registry | http://localhost:8081 |
| Services directly (debugging) | auth 8001, user 8002, product 8003, inventory 8004, order 8005, notification 8006 — each with `/docs` |
| Kafka (from the host) | `localhost:9094` |
| PostgreSQL | `localhost:5432`, user `postgres` |
| MongoDB | `mongodb://localhost:27017/?directConnection=true` |
| Redis | `localhost:6379` |
| Kafka UI (optional) | http://localhost:8088 — `docker compose --profile tools up -d kafka-ui` |

All published ports listen on `127.0.0.1` only. Clients use port 8000; direct service ports
exist for debugging.

### Request path

```
client → Nginx :8000 → api-gateway (2 replicas, least_conn) → service
```

- **Nginx** balances the gateway replicas (`least_conn`), retries a request on another
  replica if one is down, adds `X-Request-ID`, `X-Real-IP`, `X-Forwarded-For`, limits the
  body to 1 MB and writes a JSON access log. New replicas are picked up through Docker DNS
  without restarting Nginx: `docker compose up -d --scale api-gateway=3`.
- **api-gateway** checks the JWT against the auth-service JWKS (an invalid token never reaches
  a service), strips client-supplied `X-User-*` / `X-Forwarded-*` headers, applies rate limits
  (Redis token bucket: 100 rps per user, 20 rps per IP for anonymous clients, 10 logins per
  minute per IP) and answers errors as `application/problem+json`. `GET /api/v1/products/{id}`
  for customers is served over gRPC from product-service (falls back to REST if gRPC is down).
- Every response carries `X-Request-ID`, `X-Gateway-Instance` (which replica answered) and
  `RateLimit-Limit` / `RateLimit-Remaining`.

### Example: from registration to a completed order

```bash
API=localhost:8000/api/v1

# Register; the verification email arrives in Mailpit (http://localhost:8025)
curl -s $API/auth/register -H 'Content-Type: application/json' \
  -d '{"email": "buyer@example.com", "password": "a long buyer passphrase"}'
curl -s $API/auth/verify-email -H 'Content-Type: application/json' \
  -d '{"token": "<token from the link>"}'

TOKEN=$(curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email": "buyer@example.com", "password": "a long buyer passphrase"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

curl -s $API/users/me -H "$AUTH"                               # profile
curl -s "$API/products?q=teapot&price_max=2000&sort=price"      # catalog search, public

# Place an order: prices come from the catalog, the key makes retries safe
curl -s $API/orders -H "$AUTH" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"items": [{"product_id": "<product id>", "quantity": 1}]}'

curl -s $API/orders/<order id> -H "$AUTH"          # NEW → RESERVED in a moment (saga)
curl -s -X POST $API/orders/<order id>/pay -H "$AUTH"
```

Shipping and completing (`POST /orders/{id}/ship`, `/complete`), creating products and adding
stock (`POST /inventory/stock/{id}/adjust`) need a manager or administrator token (see step 4).
Every status change is emailed to the customer — see Mailpit.

Main endpoints (full list in Swagger at http://localhost:8000/docs):

| Area | Endpoints |
|------|-----------|
| auth | `POST /api/v1/auth/register`, `/verify-email`, `/resend-verification`, `/login`, `/refresh`, `/logout`, `/password`; `GET /api/v1/auth/.well-known/jwks.json` |
| users | `GET/PATCH /api/v1/users/me`; `GET /api/v1/users` (staff); `GET /api/v1/users/{id}`; `PUT /api/v1/users/{id}/roles`, `DELETE /api/v1/users/{id}` (admin) |
| catalog | `GET /api/v1/products` (search), `GET /api/v1/products/{id}`; `POST/PUT/PATCH/DELETE` (admin, `If-Match`); `POST /{id}/publish`, `/{id}/unpublish` (staff); `/api/v1/categories` |
| inventory | `GET /api/v1/inventory/stock/{product_id}`, `POST /api/v1/inventory/stock/{product_id}/adjust` (staff) |
| orders | `POST /api/v1/orders` (`Idempotency-Key` required), `GET /api/v1/orders`, `GET /api/v1/orders/{id}`, `POST /{id}/pay`, `/{id}/cancel`; `/{id}/ship`, `/{id}/complete` (staff) |
| notifications | `GET /api/v1/notifications` (journal), `GET/PUT /api/v1/notifications/templates/{key}` (admin) |
| gRPC (internal) | `orders.catalog.v1.ProductService` :50051, `orders.inventory.v1.InventoryService` :50052 |

The fake payment provider declines amounts ending in `.13` — handy to try a failed payment.

### Checks and logs

```bash
make dev-ps                              # container states
make dev-logs                            # logs of the whole stack
docker compose logs -f product-worker    # logs of one container
curl localhost:8001/health/ready         # 503 if a dependency is down
```

### Observability

```bash
make obs-up      # the stack + OpenTelemetry Collector, Jaeger, Prometheus, Loki, Alloy, Grafana
make obs-down
```

| Tool | Address | What you get |
|------|---------|--------------|
| Grafana | http://localhost:3000 | dashboards in the *Orders Platform* folder: requests (RED), order saga, Kafka and outbox; logs (Loki) and traces (Jaeger) in Explore |
| Jaeger | http://localhost:16686 | one trace per request across services: gateway → order-service → Kafka → inventory → order → notification, incl. gRPC calls |
| Prometheus | http://localhost:9090 | metrics of every API replica and worker; alert state at `/alerts` |

- **Traces.** Every service exports spans over OTLP. The trace context travels with events:
  the outbox stores `traceparent` in Kafka headers and consumers continue the same trace.
- **Logs.** JSON logs carry `trace_id` / `span_id`; Alloy ships container logs to Loki.
  In Grafana a log line links to its trace and a span links to its logs.
- **Metrics.** HTTP (rate, errors, latency by route), Kafka (consumer lag, processed events,
  DLQ), outbox (pending records, oldest record age) and business metrics (orders created,
  status transitions, saga decision time, stuck orders, reservations, emails).
- **Alerts.** `HighErrorRate`, `HighLatency`, `OutboxStuck`, `ConsumerLag`, `DLQNotEmpty`,
  `SagaStuck` — rules in `observability/prometheus/alerts.yml`, unit tests run with
  `make check-alerts`. Try it: `docker compose stop kafka`, register a user, and
  `OutboxStuck` fires within about two minutes.

Without `make obs-up` services still log `trace_id` but do not export traces.

### Seed data, end-to-end tests, load test

`make dev-up` runs `scripts/seed.py` (idempotent, also `make seed`): an administrator
(`admin@example.com`), a manager (`manager@example.com`), 5 categories and 20 products with
50 items in stock each. Passwords come from `SEED_ADMIN_PASSWORD` / `SEED_MANAGER_PASSWORD`
(local defaults: `local-dev-admin-passphrase`, `local-dev-manager-passphrase`).

```bash
make e2e    # 8 end-to-end scenarios against the running stack (about 1.5 minutes)
make load   # locust: ~500 RPS for 60 s through Nginx, report in docs/perf/report.md
```

End-to-end scenarios (`e2e/`) go through the public API only:

1. registration → email confirmation from Mailpit → order → reserve → pay → ship → complete,
   stock written off, five status emails;
2. several customers race for the last item: one reservation, the rest cancelled
   (`OUT_OF_STOCK`) with an email;
3. cancel after reservation releases stock;
4. reservation expiry cancels the order (`make e2e` shortens the TTL for the run);
5. cancelling a paid order refunds and releases stock;
6. the inventory worker is stopped while an order is placed — the order is reserved once it
   is back;
7. idempotency: the same `Idempotency-Key` returns the same order, a redelivered Kafka event
   changes nothing;
8. access rules: customers cannot ship, see other orders or order anonymously.

### Kafka and databases

```bash
# List topics
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

# Read a topic from the beginning
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic user.created --from-beginning

docker compose exec postgres psql -U postgres -d auth   # databases: auth, users, inventory, orders
docker compose exec mongo mongosh catalog
```

---

## Development

### Commands

```bash
make help              # list of all commands
make lint              # ruff, format check, layer contracts, event schemas and gRPC code up to date
make format            # auto-fix and format
make typecheck         # mypy (strict) for every package
make test              # unit tests of all packages
make test-integration  # integration tests (Docker required, testcontainers)
make export-schemas    # regenerate event JSON Schemas after changing libs/events
make proto             # regenerate gRPC code after changing proto/
make register-schemas  # register schemas in Schema Registry (done by make dev-up)
make compat-schemas    # check model compatibility with the registry
make obs-up           # stack with Jaeger, Prometheus, Grafana, Loki
make check-alerts     # validate Prometheus alert rules and their unit tests
```

Working on one service:

```bash
cd product-service
uv run pytest -q                                              # all tests with coverage
uv run pytest -q -m unit                                      # unit tests only
uv run uvicorn src.main:create_app --factory --reload --port 8003
uv run lint-imports                                           # layer contracts
```

Integration tests start PostgreSQL, MongoDB (replica set), Redis and Kafka in containers
themselves; the `make dev-up` stack is only needed for the Schema Registry tests in
`libs/events`.

### Dependencies

```bash
cd order-service && uv add sqlalchemy    # service dependency
uv add --dev <package>                   # development tool (from the root)
```

`uv.lock` is never edited by hand.

### Database migrations

Migrations are applied automatically when a service container starts (`alembic upgrade head`).
New migration after changing tables in `src/db.py`:

```bash
cd user-service
DATABASE_URL=postgresql+asyncpg://users:local-dev-users@localhost:5432/users \
  uv run alembic revision --autogenerate -m "describe the change"
```

Applied migrations are never edited — create a new one instead.

### Adding a service

1. Copy the layout of an existing service: `pyproject.toml`, `Dockerfile`, `src/`, `tests/`.
2. Add the service to `SERVICES` in the `Makefile` and to `docker-compose.yml` (API and worker).
3. If it needs its own PostgreSQL database, add it to `scripts/postgres-init-databases.sh`.

### Docker images

Images are built from the repository root because they need `libs/` and `uv.lock`:

```bash
docker build -f product-service/Dockerfile -t orders/product-service:dev .
```

Two-stage build: dependencies via `uv sync --frozen --no-dev`, the process runs as an
unprivileged user, the image has a `HEALTHCHECK`.

---

## Code conventions

- **Layers.** `api/` handles HTTP only, logic lives in `services/`, database access in
  `repositories/`, `domain/` has no I/O. import-linter enforces this in `make lint`.
- **Money.** Always `Decimal`, never `float`: `NUMERIC(12,2)` in PostgreSQL, `Decimal128` in
  MongoDB, a string (`"10.10"`) in JSON, events and gRPC.
- **Time.** Timezone-aware `datetime` in UTC only; `TIMESTAMPTZ` in PostgreSQL.
- **Events** are published only through the transactional outbox, in the same transaction as
  the data change.
- **Idempotency.** Every consumer stores `event_id` in `processed_events` in the handler's
  transaction; redelivered events are skipped. The Kafka offset is committed after processing.
- **Event contract** changes only in `libs/events` and only backward compatibly: new fields
  get defaults, existing fields are not removed or renamed.
- **Secrets** never go into code, tests or logs; logs mask passwords and tokens automatically.

## Git workflow

- `main` is protected: changes only through pull requests.
- One feature — one branch (`feat/...`, `fix/...`, `docs/...`, `chore/...`) and one PR.
- Commit messages are in English.
- Before opening a PR: `make lint typecheck test` and the integration tests of the changed
  packages.

---

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| `make dev-up`: `port is already allocated` | Override the port in `.env` (`GATEWAY_HOST_PORT=8080`, `POSTGRES_HOST_PORT=15432`, `AUTH_SERVICE_HOST_PORT=18001`, ...) |
| `429 Too Many Requests` from the API | Rate limit of api-gateway; wait `Retry-After` seconds |
| `502` / `504` from the API | A service is down or slow: `make dev-ps`, `docker compose logs <service>` |
| `Cannot connect to the Docker daemon` | Start Docker Desktop / OrbStack / Colima, then `make doctor` |
| A container is `unhealthy` | `docker compose logs <service>`, then `make dev-down && make dev-up` |
| Need clean data | `make dev-reset && make dev-up` |
| `ModuleNotFoundError: src` in tests | Run pytest from the service directory: `cd <service> && uv run pytest` |
| Missing dependencies after `git pull` | `make install` |
| `make lint` says the gRPC code is outdated | `make proto` |
| Random `401 invalid or expired token`, builds hang (macOS, after sleep) | The Docker VM clock lags behind: compare `date -u` with `docker run --rm alpine date -u`; restart Docker Desktop or sync the clock: `docker run --rm --privileged alpine date -u -s "@$(date -u +%s)"` |

## License

[MIT](LICENSE)
