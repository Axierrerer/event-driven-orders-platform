#!/bin/sh
# Создаёт отдельную БД и роль на каждый PG-сервис.
# Идемпотентно: запускается контейнером postgres-init при каждом `make dev-up`.
set -eu

export PGHOST="${PGHOST:-postgres}" PGUSER="${PGUSER:-postgres}"

create_db() {
    psql -v ON_ERROR_STOP=1 --dbname postgres -v name="$1" -v password="$2" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'name', :'password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'name') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'name', :'password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'name', :'name')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'name') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'name') \gexec
SQL
    echo "database ok: $1"
}

create_db auth "$AUTH_DB_PASSWORD"
create_db users "$USERS_DB_PASSWORD"
create_db inventory "$INVENTORY_DB_PASSWORD"
create_db orders "$ORDERS_DB_PASSWORD"
