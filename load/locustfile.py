"""Нагрузочный профиль: 80% поиск, 15% карточка товара, 5% оформление заказа.

Запуск: make load (поднимает лимиты gateway на время теста и пишет отчёт).
"""

import os
import random
import uuid
from urllib.parse import quote

from locust import FastHttpUser, constant_throughput, events, task

ADMIN_EMAIL = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "local-dev-admin-passphrase")
QUERIES = ["чайник", "чашка", "плед", "нож", "ваза", "свеча", "корзина", "банка"]
# Каждый пользователь делает ~5 запросов в секунду: 100 пользователей ≈ 500 RPS
RPS_PER_USER = float(os.environ.get("LOAD_RPS_PER_USER", "5"))

PRODUCTS: list[str] = []
TOKEN: dict[str, str] = {}


@events.test_start.add_listener
def prepare(environment, **_kwargs):  # type: ignore[no-untyped-def]
    """Один раз: id товаров и токен покупателя (администратор из seed — email подтверждён)."""
    import httpx

    host = environment.host
    with httpx.Client(base_url=host, timeout=10) as client:
        page = client.get("/api/v1/products", params={"limit": 100}).json()
        PRODUCTS.extend(p["id"] for p in page["items"])
        login = client.post(
            "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        login.raise_for_status()
        TOKEN["value"] = login.json()["access_token"]
    if not PRODUCTS:
        raise RuntimeError("catalog is empty: run make seed")


class Shopper(FastHttpUser):
    wait_time = constant_throughput(RPS_PER_USER)

    @task(80)
    def search(self) -> None:
        query = quote(random.choice(QUERIES))  # noqa: S311 — кириллица в URL кодируется
        self.client.get(f"/api/v1/products?q={query}&limit=20", name="GET /products?q=")

    @task(15)
    def product_card(self) -> None:
        self.client.get(
            f"/api/v1/products/{random.choice(PRODUCTS)}",  # noqa: S311
            name="GET /products/{id}",
        )

    @task(5)
    def checkout(self) -> None:
        with self.client.post(
            "/api/v1/orders",
            json={"items": [{"product_id": random.choice(PRODUCTS), "quantity": 1}]},  # noqa: S311
            headers={
                "Authorization": f"Bearer {TOKEN['value']}",
                "Idempotency-Key": f"load-{uuid.uuid4()}",
            },
            name="POST /orders",
            catch_response=True,
        ) as response:
            # 409 «товар закончился» — корректный ответ бизнес-логики, а не сбой
            if response.status_code in (201, 409):
                response.success()
