# Event-Driven Order Processing Platform

[English](README.md) | **Русский**

Платформа обработки заказов для небольшого e-commerce-магазина: каталог товаров,
пользователи и роли, оформление заказов, учёт запасов и уведомления.

Система состоит из микросервисов на Python (FastAPI, asyncio). Сервисы общаются
асинхронно через Kafka и синхронно через REST и gRPC. Заказ проходит путь от оформления
до доставки как **сага на хореографии**: каждый сервис реагирует на события других и при
сбое публикует компенсирующие события.

## Статус

| Компонент | Состояние |
|-----------|-----------|
| Локальный стенд (`make dev-up`), монорепо, линтеры, тесты | ✅ готово |
| `libs/events` — контракт событий Kafka | ✅ готово |
| `libs/platform` — outbox, идемпотентный consumer, авторизация, логи | ✅ готово |
| `auth-service` | ✅ готово |
| `user-service` | ✅ готово |
| `product-service` (REST + gRPC) | ✅ готово |
| `inventory-service` (REST + gRPC) | ✅ готово |
| `order-service` с сагой заказа | ✅ готово |
| `notification-service` (письма, rate limiting) | ✅ готово |
| `api-gateway` (маршрутизация, JWT, rate limiting, единый Swagger) за Nginx | ✅ готово |
| Observability: трейсы (OpenTelemetry → Jaeger), метрики (Prometheus), логи (Loki), дашборды Grafana, алерты | ✅ готово |
| Kubernetes (k3d + Helm), проверки безопасности, e2e | ⏳ в планах |

---

## Содержание

- [Архитектура](#архитектура)
- [Стек](#стек)
- [Структура репозитория](#структура-репозитория)
- [Быстрый старт](#быстрый-старт)
- [Как пользоваться стендом](#как-пользоваться-стендом)
- [Разработка](#разработка)
- [Правила кода](#правила-кода)
- [Работа с git](#работа-с-git)
- [Решение проблем](#решение-проблем)

---

## Архитектура

```mermaid
flowchart LR
    client([Клиент]) -->|HTTP :8000| nginx[Nginx<br/>reverse proxy + LB]
    nginx -->|least_conn| gw[api-gateway × N]

    gw -->|REST| auth[auth-service]
    gw -->|REST| users[user-service]
    gw -->|REST / gRPC| product[product-service]
    gw -->|REST| inventory[inventory-service]
    gw -->|REST| orders[order-service]

    orders -->|gRPC: наличие| inventory
    orders -->|gRPC: цены| product

    auth & users & product & inventory & orders <-->|события| kafka[(Kafka)]
    kafka --> notify[notification-service]
    notify -->|SMTP| mail[(Email)]
```

### Сервисы

| Сервис | Назначение | Хранилище | Протоколы |
|--------|-----------|-----------|-----------|
| `nginx` | Публичная точка входа: reverse proxy и балансировщик реплик api-gateway | — | HTTP |
| `api-gateway` | Маршрутизация, проверка JWT, rate limiting, единый Swagger; карточки товаров по gRPC | Redis | REST, gRPC |
| `auth-service` | Регистрация, подтверждение email, JWT access + refresh | PostgreSQL | REST |
| `user-service` | Профили пользователей и роли (`ROLE_USER`, `ROLE_MANAGER`, `ROLE_ADMIN`) | PostgreSQL | REST, Kafka |
| `product-service` | Каталог: CRUD, публикация, полнотекстовый поиск и фильтры | MongoDB, Redis | REST, gRPC, Kafka |
| `inventory-service` | Остатки и резервы товаров | PostgreSQL | gRPC, Kafka |
| `order-service` | Заказы и их жизненный цикл | PostgreSQL | REST, gRPC, Kafka |
| `notification-service` | Письма о статусах заказа, rate limiting по пользователю | MongoDB, Redis | Kafka |

Каждый сервис, который публикует или читает события, запускается двумя контейнерами из
одного образа: API (`<service>`) и фоновый worker (`<service>-worker`), который отправляет
outbox в Kafka и обрабатывает входящие события.

### Жизненный цикл заказа

```mermaid
stateDiagram-v2
    [*] --> NEW: заказ оформлен
    NEW --> RESERVED: inventory.reserved
    NEW --> CANCELLED: inventory.reservation-failed
    RESERVED --> PAID: оплата
    RESERVED --> CANCELLED: отмена / резерв истёк
    PAID --> SHIPPED: отгрузка
    PAID --> CANCELLED: отмена с возвратом денег
    SHIPPED --> COMPLETED
    COMPLETED --> [*]
    CANCELLED --> [*]
```

### События Kafka

| Топик | Ключ | Публикует | Читают |
|-------|------|-----------|--------|
| `user.created` | user_id | auth-service | user-service, notification-service |
| `user.verification-requested` | user_id | auth-service | notification-service |
| `user.roles-changed` | user_id | user-service | auth-service |
| `product.changed` | product_id | product-service | inventory-service |
| `order.created` | order_id | order-service | inventory-service, notification-service |
| `inventory.reserved` | order_id | inventory-service | order-service |
| `inventory.reservation-failed` | order_id | inventory-service | order-service |
| `inventory.released` | order_id | inventory-service | order-service |
| `order.status-changed` | order_id | order-service | inventory-service, notification-service |

У каждого топика есть очередь ошибок `<топик>.dlq`: туда попадают сообщения, которые не
удалось обработать после повторных попыток. Схемы событий — это Pydantic-модели в
`libs/events`. Сгенерированные из них JSON Schema лежат в `libs/events/schemas` и
регистрируются в Schema Registry с режимом совместимости `BACKWARD`.

---

## Стек

| Область | Технологии |
|---------|-----------|
| Язык и веб | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, Uvicorn |
| Базы данных | PostgreSQL 16 (SQLAlchemy 2 async + asyncpg, Alembic), MongoDB 7 (Motor), Redis 7 (redis.asyncio) |
| Обмен сообщениями | Apache Kafka (KRaft), Confluent Schema Registry (JSON Schema), confluent-kafka |
| Синхронные вызовы | REST (httpx), gRPC (grpcio) |
| Аутентификация | JWT RS256 + JWKS (PyJWT), Argon2id (pwdlib) |
| Зависимости | uv (workspace, единый `uv.lock`) |
| Качество | ruff (линтер и форматирование), mypy (strict), import-linter, pytest + pytest-asyncio, pytest-cov, testcontainers |
| Инфраструктура | Docker, docker-compose, Nginx; Kubernetes (k3d) и Helm — в планах |
| Observability | OpenTelemetry, Jaeger, Prometheus, Grafana, Loki, Grafana Alloy |
| Почта (локально) | Mailpit |

---

## Структура репозитория

```
.
├── pyproject.toml              # корень uv workspace + настройки ruff и mypy
├── uv.lock                     # единый lock-файл зависимостей
├── Makefile                    # все рабочие команды (make help)
├── docker-compose.yml          # локальный стенд
├── nginx/nginx.conf            # публичная точка входа: reverse proxy + балансировщик
├── observability/             # Collector, Prometheus (+ алерты), Loki/Alloy, Grafana
├── proto/                      # .proto внутренних gRPC API
├── scripts/                    # все скрипты проекта
│   ├── doctor.sh               #   проверка окружения разработчика
│   ├── generate-proto.sh       #   генерация Python-кода из proto/
│   ├── postgres-init-databases.sh  # базы данных и роли сервисов
│   └── kafka-create-topics.sh  #   топики и их DLQ
├── libs/
│   ├── events/                 # контракт событий Kafka (Pydantic-модели + JSON Schema)
│   ├── platform/               # outbox, consumer, JWT, логи, health, блокировки, worker
│   └── proto/                  # сгенерированный gRPC-код (пакет orders_proto)
└── <service>/                  # auth-service, user-service, product-service, ...
    ├── pyproject.toml
    ├── Dockerfile
    ├── alembic.ini, migrations/   # сервисы на PostgreSQL
    ├── src/
    │   ├── main.py             # фабрика FastAPI-приложения
    │   ├── worker.py           # фоновый процесс: outbox relay + consumer Kafka
    │   ├── config.py           # настройки из переменных окружения
    │   ├── api/                # только HTTP: роуты, схемы запросов и ответов
    │   ├── services/           # бизнес-сценарии, транзакции
    │   ├── domain/             # чистые модели и правила, без I/O
    │   └── repositories/       # доступ к базе данных
    └── tests/
        ├── unit/
        └── integration/
```

Код сервиса лежит прямо в `<service>/src/` и импортируется как `src.*`. Каждый сервис входит
в uv workspace как «виртуальный» участник: uv ставит его зависимости, а сам код пакетом не
ставится. Библиотеки из `libs/` устанавливаются как пакеты `events`, `platform_lib` и
`orders_proto`.

---

## Быстрый старт

### 1. Что нужно установить

| Инструмент | Версия | Зачем |
|-----------|--------|-------|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | Python и зависимости |
| Docker Desktop / OrbStack / Colima | Engine ≥ 25, Compose v2 | локальный стенд, testcontainers |
| GNU Make | ≥ 3.81 | команды проекта |
| git | ≥ 2.40 | — |
| k3d, kubectl, helm, kubeseal, trivy, grpcurl | актуальные | Kubernetes и сканирование (следующие этапы) |

**macOS:**

```bash
xcode-select --install                                   # make, git
brew install uv k3d kubectl helm kubeseal trivy grpcurl
brew install --cask docker                               # или: brew install orbstack
uv python install 3.12
```

**Linux / Windows (WSL2):** установите Docker, затем:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
```

Стенд занимает около 1 GB памяти; для разработки хватает 2 CPU и 8 GB RAM.

### 2. Установка проекта

```bash
git clone https://github.com/Axierrerer/event-driven-orders-platform.git
cd event-driven-orders-platform

make doctor     # проверит, что все инструменты на месте и Docker запущен
make install    # uv sync --all-packages: все сервисы и библиотеки в одном .venv
```

### 3. Запуск стенда

```bash
make dev-up
```

Одна команда собирает образы, поднимает инфраструктуру, создаёт базы данных, топики Kafka и
схемы событий, применяет миграции, запускает все сервисы и worker'ы, две реплики api-gateway и
Nginx перед ними и ждёт, пока всё станет healthy. Обычно это около 30 секунд, при первом запуске
дольше из-за скачивания образов.

Файл `.env` для запуска **не нужен**: у всех переменных в `docker-compose.yml` есть значения
по умолчанию для локальной разработки. Если нужно что-то переопределить, например занятый
порт, создайте `.env` в корне:

```dotenv
GATEWAY_HOST_PORT=8080      # порт Nginx на хосте
GATEWAY_REPLICAS=3          # сколько реплик api-gateway стоит за Nginx
POSTGRES_HOST_PORT=15432
```

`.env` в git не попадает.

### 4. Первый администратор

Пользователи с `ROLE_ADMIN` через публичный API не создаются. Роль администратора
автоматически получает пользователь с email из `BOOTSTRAP_ADMIN_EMAIL`
(по умолчанию `admin@example.com`):

```bash
docker compose exec -e NEW_USER_PASSWORD='придумайте длинную фразу-пароль' \
  auth-service python -m src.cli create-user --email admin@example.com --verified
```

Пароль читается из переменной окружения, а не из аргументов, поэтому не попадает в список
процессов. Через несколько секунд роль приходит через Kafka (`user.created` → user-service →
`user.roles-changed` → auth-service), и в токене следующего входа уже есть `ROLE_ADMIN`.

### 5. Остановка

```bash
make dev-down     # остановить, данные в томах сохраняются
make dev-reset    # остановить и удалить все данные
```

---

## Как пользоваться стендом

### Адреса

| Что | Адрес |
|-----|-------|
| **API (Nginx → api-gateway)** | http://localhost:8000 |
| **Swagger всей платформы** | http://localhost:8000/docs |
| Mailpit (письма) | http://localhost:8025 |
| Schema Registry | http://localhost:8081 |
| Сервисы напрямую (отладка) | auth 8001, user 8002, product 8003, inventory 8004, order 8005, notification 8006 — у каждого `/docs` |
| Kafka (с хоста) | `localhost:9094` |
| PostgreSQL | `localhost:5432`, пользователь `postgres` |
| MongoDB | `mongodb://localhost:27017/?directConnection=true` |
| Redis | `localhost:6379` |
| Kafka UI (по желанию) | http://localhost:8088 — `docker compose --profile tools up -d kafka-ui` |

Все опубликованные порты слушают только `127.0.0.1`. Клиенты работают через порт 8000; прямые
порты сервисов оставлены для отладки.

### Путь запроса

```
клиент → Nginx :8000 → api-gateway (2 реплики, least_conn) → сервис
```

- **Nginx** балансирует реплики gateway (`least_conn`), при падении реплики повторяет запрос на
  соседней, добавляет `X-Request-ID`, `X-Real-IP`, `X-Forwarded-For`, ограничивает тело запроса
  1 MB и пишет access log в JSON. Новые реплики подхватываются через DNS Docker без перезапуска
  Nginx: `docker compose up -d --scale api-gateway=3`.
- **api-gateway** проверяет JWT по JWKS auth-service (невалидный токен до сервисов не доходит),
  вырезает присланные клиентом `X-User-*` / `X-Forwarded-*`, применяет rate limit (token bucket
  в Redis: 100 rps на пользователя, 20 rps на IP для анонимов, 10 входов в минуту с IP) и
  отвечает ошибками в формате `application/problem+json`. `GET /api/v1/products/{id}` для
  покупателей обслуживается по gRPC из product-service (при недоступности gRPC — по REST).
- В каждом ответе есть `X-Request-ID`, `X-Gateway-Instance` (какая реплика ответила) и
  `RateLimit-Limit` / `RateLimit-Remaining`.

### Пример: от регистрации до выполненного заказа

```bash
API=localhost:8000/api/v1

# Регистрация; письмо подтверждения придёт в Mailpit (http://localhost:8025)
curl -s $API/auth/register -H 'Content-Type: application/json' \
  -d '{"email": "buyer@example.com", "password": "a long buyer passphrase"}'
curl -s $API/auth/verify-email -H 'Content-Type: application/json' \
  -d '{"token": "<токен из ссылки>"}'

TOKEN=$(curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email": "buyer@example.com", "password": "a long buyer passphrase"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

curl -s $API/users/me -H "$AUTH"                               # профиль
curl -s -G $API/products --data-urlencode 'q=чайник' -d price_max=2000 -d sort=price  # каталог

# Заказ: цены берутся из каталога, ключ делает повтор запроса безопасным
curl -s $API/orders -H "$AUTH" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"items": [{"product_id": "<id товара>", "quantity": 1}]}'

curl -s $API/orders/<id заказа> -H "$AUTH"          # через мгновение NEW → RESERVED (сага)
curl -s -X POST $API/orders/<id заказа>/pay -H "$AUTH"
```

Отгрузка и завершение (`POST /orders/{id}/ship`, `/complete`), создание товаров и пополнение
остатков (`POST /inventory/stock/{id}/adjust`) требуют токена менеджера или администратора
(см. шаг 4). О каждой смене статуса покупатель получает письмо — смотрите Mailpit.

Основные эндпоинты (полный список — в Swagger на http://localhost:8000/docs):

| Раздел | Эндпоинты |
|--------|-----------|
| auth | `POST /api/v1/auth/register`, `/verify-email`, `/resend-verification`, `/login`, `/refresh`, `/logout`, `/password`; `GET /api/v1/auth/.well-known/jwks.json` |
| пользователи | `GET/PATCH /api/v1/users/me`; `GET /api/v1/users` (персонал); `GET /api/v1/users/{id}`; `PUT /api/v1/users/{id}/roles`, `DELETE /api/v1/users/{id}` (администратор) |
| каталог | `GET /api/v1/products` (поиск), `GET /api/v1/products/{id}`; `POST/PUT/PATCH/DELETE` (администратор, `If-Match`); `POST /{id}/publish`, `/{id}/unpublish` (персонал); `/api/v1/categories` |
| склад | `GET /api/v1/inventory/stock/{product_id}`, `POST /api/v1/inventory/stock/{product_id}/adjust` (персонал) |
| заказы | `POST /api/v1/orders` (нужен `Idempotency-Key`), `GET /api/v1/orders`, `GET /api/v1/orders/{id}`, `POST /{id}/pay`, `/{id}/cancel`; `/{id}/ship`, `/{id}/complete` (персонал) |
| уведомления | `GET /api/v1/notifications` (журнал), `GET/PUT /api/v1/notifications/templates/{key}` (администратор) |
| gRPC (внутренний) | `orders.catalog.v1.ProductService` :50051, `orders.inventory.v1.InventoryService` :50052 |

Имитация платёжного провайдера отклоняет суммы, оканчивающиеся на `.13`, — так можно
проверить неудачную оплату.

### Проверка и логи

```bash
make dev-ps                              # состояние контейнеров
make dev-logs                            # логи всего стенда
docker compose logs -f product-worker    # логи одного контейнера
curl localhost:8001/health/ready         # 503, если какая-то зависимость недоступна
```

### Observability

```bash
make obs-up      # стенд + OpenTelemetry Collector, Jaeger, Prometheus, Loki, Alloy, Grafana
make obs-down
```

| Инструмент | Адрес | Что там |
|-----------|-------|---------|
| Grafana | http://localhost:3000 | дашборды в папке *Orders Platform*: запросы (RED), сага заказа, Kafka и outbox; логи (Loki) и трейсы (Jaeger) в Explore |
| Jaeger | http://localhost:16686 | один трейс на запрос через все сервисы: gateway → order-service → Kafka → inventory → order → notification, включая gRPC |
| Prometheus | http://localhost:9090 | метрики всех реплик API и worker'ов; состояние алертов на `/alerts` |

- **Трейсы.** Каждый сервис отправляет спаны по OTLP. Контекст трейса едет вместе с событием:
  outbox кладёт `traceparent` в заголовки Kafka, consumer продолжает тот же трейс.
- **Логи.** В JSON-логах есть `trace_id` / `span_id`; Alloy отправляет логи контейнеров в Loki.
  В Grafana из строки лога можно перейти к трейсу, а из спана — к его логам.
- **Метрики.** HTTP (запросы, ошибки, задержка по маршрутам), Kafka (отставание consumer'ов,
  обработанные события, DLQ), outbox (неотправленные записи, возраст самой старой) и
  бизнес-метрики (созданные заказы, переходы статусов, время решения саги, зависшие заказы,
  резервы, письма).
- **Алерты.** `HighErrorRate`, `HighLatency`, `OutboxStuck`, `ConsumerLag`, `DLQNotEmpty`,
  `SagaStuck` — правила в `observability/prometheus/alerts.yml`, unit-тесты запускаются
  `make check-alerts`. Попробуйте: `docker compose stop kafka`, зарегистрируйте пользователя —
  примерно через две минуты сработает `OutboxStuck`.

Без `make obs-up` сервисы всё равно пишут `trace_id` в логи, но трейсы не экспортируют.

### Kafka и базы данных

```bash
# Список топиков
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

# Прочитать топик с начала
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic user.created --from-beginning

docker compose exec postgres psql -U postgres -d auth   # базы: auth, users, inventory, orders
docker compose exec mongo mongosh catalog
```

---

## Разработка

### Команды

```bash
make help              # список всех команд
make lint              # ruff, формат, правила слоёв, актуальность схем событий и gRPC-кода
make format            # автоисправление и форматирование
make typecheck         # mypy (strict) по каждому пакету
make test              # unit-тесты всех пакетов
make test-integration  # интеграционные тесты (нужен Docker, testcontainers)
make export-schemas    # перегенерировать JSON Schema событий после изменения libs/events
make proto             # перегенерировать gRPC-код после изменения proto/
make register-schemas  # зарегистрировать схемы в Schema Registry (делает make dev-up)
make compat-schemas    # проверить совместимость моделей со схемами в реестре
make obs-up           # стенд с Jaeger, Prometheus, Grafana, Loki
make check-alerts     # проверить правила алертов Prometheus и их unit-тесты
```

Работа с одним сервисом:

```bash
cd product-service
uv run pytest -q                                              # все тесты с покрытием
uv run pytest -q -m unit                                      # только unit-тесты
uv run uvicorn src.main:create_app --factory --reload --port 8003
uv run lint-imports                                           # правила слоёв
```

Интеграционные тесты сами поднимают PostgreSQL, MongoDB (replica set), Redis и Kafka в
контейнерах; стенд `make dev-up` нужен только для тестов Schema Registry в `libs/events`.

### Зависимости

```bash
cd order-service && uv add sqlalchemy    # зависимость сервиса
uv add --dev <пакет>                     # инструмент разработки (из корня)
```

`uv.lock` руками не редактируется.

### Миграции базы данных

Миграции применяются автоматически при старте контейнера сервиса (`alembic upgrade head`).
Новая миграция после изменения таблиц в `src/db.py`:

```bash
cd user-service
DATABASE_URL=postgresql+asyncpg://users:local-dev-users@localhost:5432/users \
  uv run alembic revision --autogenerate -m "describe the change"
```

Применённые миграции не правятся — вместо этого создаётся новая.

### Новый сервис

1. Скопируйте структуру существующего сервиса: `pyproject.toml`, `Dockerfile`, `src/`, `tests/`.
2. Добавьте сервис в `SERVICES` в `Makefile` и в `docker-compose.yml` (API и worker).
3. Если сервису нужна своя база PostgreSQL, добавьте её в `scripts/postgres-init-databases.sh`.

### Docker-образы

Образы собираются из корня репозитория, потому что им нужны `libs/` и `uv.lock`:

```bash
docker build -f product-service/Dockerfile -t orders/product-service:dev .
```

Образ двухстадийный: зависимости ставятся через `uv sync --frozen --no-dev`, процесс
запускается под непривилегированным пользователем, у образа есть `HEALTHCHECK`.

---

## Правила кода

- **Слои.** `api/` отвечает только за HTTP, логика живёт в `services/`, доступ к БД — в
  `repositories/`, `domain/` не зависит от I/O. Правила проверяет import-linter в `make lint`.
- **Деньги.** Только `Decimal`, никогда `float`: `NUMERIC(12,2)` в PostgreSQL, `Decimal128` в
  MongoDB, строка (`"10.10"`) в JSON, событиях и gRPC.
- **Время.** Только `datetime` с часовым поясом UTC; в PostgreSQL — `TIMESTAMPTZ`.
- **События** публикуются только через transactional outbox, в той же транзакции, что и
  изменение данных.
- **Идемпотентность.** Каждый consumer сохраняет `event_id` в `processed_events` в транзакции
  обработчика; повторно доставленное событие пропускается. Offset Kafka коммитится только
  после обработки.
- **Контракт событий** меняется только в `libs/events` и только обратно совместимо: новые
  поля добавляются со значением по умолчанию, существующие не удаляются и не переименовываются.
- **Секреты** не попадают в код, тесты и логи; пароли и токены в логах маскируются автоматически.

## Работа с git

- `main` защищена: изменения только через pull request.
- Одна задача — одна ветка (`feat/...`, `fix/...`, `docs/...`, `chore/...`) и один PR.
- Сообщения коммитов — на английском.
- Перед PR: `make lint typecheck test` и интеграционные тесты изменённых пакетов.

---

## Решение проблем

| Симптом | Что делать |
|---------|-----------|
| `make dev-up`: `port is already allocated` | Переопределите порт в `.env` (`GATEWAY_HOST_PORT=8080`, `POSTGRES_HOST_PORT=15432`, `AUTH_SERVICE_HOST_PORT=18001` и т. п.) |
| API отвечает `429 Too Many Requests` | Сработал rate limit api-gateway; подождите `Retry-After` секунд |
| API отвечает `502` / `504` | Сервис недоступен или медленный: `make dev-ps`, `docker compose logs <сервис>` |
| `Cannot connect to the Docker daemon` | Запустите Docker Desktop / OrbStack / Colima, затем `make doctor` |
| Контейнер в статусе `unhealthy` | `docker compose logs <сервис>`, затем `make dev-down && make dev-up` |
| Нужно начать с чистыми данными | `make dev-reset && make dev-up` |
| `ModuleNotFoundError: src` в тестах | Запускайте pytest из каталога сервиса: `cd <сервис> && uv run pytest` |
| После `git pull` не хватает зависимостей | `make install` |
| `make lint` пишет, что gRPC-код устарел | `make proto` |

## Лицензия

[MIT](LICENSE)
