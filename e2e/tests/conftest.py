"""Сквозные сценарии против запущенного стенда: всё — через публичный API (Nginx).

Нужны `make dev-up` (он же выполняет seed). Адреса и пароли — из окружения.
"""

import os
import re
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

API = os.environ.get("E2E_API_URL", "http://localhost:8000/api/v1")
MAILPIT = os.environ.get("E2E_MAILPIT_URL", "http://localhost:8025")
ADMIN_EMAIL = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "local-dev-admin-passphrase")
MANAGER_EMAIL = "manager@example.com"
MANAGER_PASSWORD = os.environ.get("SEED_MANAGER_PASSWORD", "local-dev-manager-passphrase")
TIMEOUT = 30.0
# compose — локальный стенд; k8s — кластер (make k3d-e2e, CD): самоподписанный TLS, kubectl
TARGET = os.environ.get("E2E_TARGET", "compose")
NAMESPACE = os.environ.get("E2E_NAMESPACE", "orders")
TLS_VERIFY = os.environ.get("E2E_TLS_VERIFY", "1") != "0"


def wait_for[T](probe: Callable[[], T | None], what: str, timeout: float = TIMEOUT) -> T:
    """Поллинг до непустого результата (события обрабатываются асинхронно)."""
    return wait_until(probe, bool, what, timeout)  # type: ignore[arg-type]


def wait_until[T](
    fetch: Callable[[], T], predicate: Callable[[T], bool], what: str, timeout: float = TIMEOUT
) -> T:
    """Повторяет fetch(), пока predicate(результат) не станет истинным."""
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if predicate(value):
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timeout waiting for {what}; last value: {value!r}")
        time.sleep(0.3)


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)  # noqa: S603, S607


def kubectl(*args: str) -> None:
    subprocess.run(["kubectl", "-n", NAMESPACE, *args], check=True, capture_output=True)  # noqa: S603, S607


def stop_worker(name: str) -> None:
    """Остановить воркер (например, inventory-worker) и дождаться, пока он завершится."""
    if TARGET == "k8s":
        kubectl("scale", f"deploy/{name}", "--replicas=0")
        service = name.replace("-worker", "-service")
        selector = f"app.kubernetes.io/name={service},app.kubernetes.io/component=worker"
        kubectl("wait", "--for=delete", "pod", "-l", selector, "--timeout=90s")
    else:
        compose("stop", name)


def start_worker(name: str) -> None:
    if TARGET == "k8s":
        kubectl("scale", f"deploy/{name}", "--replicas=1")
        kubectl("rollout", "status", f"deploy/{name}", "--timeout=120s")
    else:
        compose("start", name)


@dataclass
class User:
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class Platform:
    def __init__(self, client: httpx.Client) -> None:
        self.http = client

    # ---------- пользователи ----------

    def login(self, email: str, password: str) -> User:
        response = self.http.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        return User(email, response.json()["access_token"])

    def register_verified(self) -> User:
        email = f"e2e-{uuid.uuid4().hex[:12]}@example.com"
        password = f"e2e passphrase {uuid.uuid4().hex[:8]}"
        response = self.http.post(
            f"{API}/auth/register", json={"email": email, "password": password}
        )
        assert response.status_code == 201, response.text

        message = wait_for(
            lambda: self.find_email(email, "Подтвердите email"), "verification email"
        )
        token = re.search(r"token=([\w-]+)", self.email_text(message["ID"]))
        assert token, "verification link not found in the email"
        verified = self.http.post(f"{API}/auth/verify-email", json={"token": token.group(1)})
        assert verified.status_code == 204, verified.text
        return self.login(email, password)

    # ---------- письма (Mailpit) ----------

    def find_email(self, to: str, subject_part: str) -> dict[str, Any] | None:
        messages = self.http.get(
            f"{MAILPIT}/api/v1/search", params={"query": f"to:{to}", "limit": 50}
        ).json()["messages"]
        return next((m for m in messages if subject_part in m["Subject"]), None)

    def email_subjects(self, to: str) -> list[str]:
        messages = self.http.get(
            f"{MAILPIT}/api/v1/search", params={"query": f"to:{to}", "limit": 50}
        ).json()["messages"]
        return [m["Subject"] for m in messages]

    def email_text(self, message_id: str) -> str:
        return str(self.http.get(f"{MAILPIT}/api/v1/message/{message_id}").json()["Text"])

    # ---------- каталог и склад ----------

    def product_with_stock(self, admin: User, stock: int, price: str = "100.00") -> str:
        sku = f"E2E-{uuid.uuid4().hex[:10]}"
        created = self.http.post(
            f"{API}/products",
            json={"sku": sku, "name": f"E2E товар {sku}", "price": price, "is_published": True},
            headers=admin.headers,
        )
        assert created.status_code == 201, created.text
        product_id = str(created.json()["id"])
        url = f"{API}/inventory/stock/{product_id}"
        wait_for(lambda: self.http.get(url, headers=admin.headers).status_code == 200, "stock row")
        if stock:
            self.http.post(
                f"{url}/adjust", json={"delta": stock, "reason": "e2e"}, headers=admin.headers
            ).raise_for_status()
        return product_id

    def stock(self, staff: User, product_id: str) -> dict[str, int]:
        response = self.http.get(f"{API}/inventory/stock/{product_id}", headers=staff.headers)
        response.raise_for_status()
        return dict(response.json())

    # ---------- заказы ----------

    def place_order(
        self, user: User, items: list[tuple[str, int]], key: str | None = None
    ) -> httpx.Response:
        return self.http.post(
            f"{API}/orders",
            json={"items": [{"product_id": pid, "quantity": qty} for pid, qty in items]},
            headers={**user.headers, "Idempotency-Key": key or f"e2e-{uuid.uuid4()}"},
        )

    def order(self, user: User, order_id: str) -> dict[str, Any]:
        response = self.http.get(f"{API}/orders/{order_id}", headers=user.headers)
        response.raise_for_status()
        return dict(response.json())

    def wait_status(self, user: User, order_id: str, status: str) -> dict[str, Any]:
        return wait_until(
            lambda: self.order(user, order_id),
            lambda order: order["status"] == status,
            f"order {order_id} to become {status}",
        )

    def action(self, user: User, order_id: str, name: str, **body: Any) -> httpx.Response:
        return self.http.post(
            f"{API}/orders/{order_id}/{name}", json=body or None, headers=user.headers
        )


@pytest.fixture(scope="session")
def platform() -> Iterator[Platform]:
    with httpx.Client(timeout=15, verify=TLS_VERIFY) as client:
        try:
            client.get(API.rsplit("/api/", 1)[0] + "/health/ready").raise_for_status()
        except httpx.HTTPError as exc:
            pytest.exit(f"stack is not running ({exc}); start it with `make dev-up`", 2)
        yield Platform(client)


@pytest.fixture(scope="session")
def admin(platform: Platform) -> User:
    return platform.login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def manager(platform: Platform) -> User:
    return platform.login(MANAGER_EMAIL, MANAGER_PASSWORD)


@pytest.fixture
def buyer(platform: Platform) -> User:
    return platform.register_verified()
