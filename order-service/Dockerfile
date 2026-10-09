# Сборка из корня репозитория: docker build -f order-service/Dockerfile .
FROM python:3.12-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY order-service/pyproject.toml ./order-service/pyproject.toml
RUN uv sync --frozen --no-dev --no-editable --package order-service

FROM python:3.12-slim-trixie
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /app/.venv /app/.venv
WORKDIR /app/service
COPY order-service/alembic.ini ./alembic.ini
COPY order-service/migrations ./migrations
COPY order-service/src ./src
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8005
USER app
EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health/live', timeout=2)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.main:create_app --factory --host 0.0.0.0 --port $PORT --proxy-headers"]
