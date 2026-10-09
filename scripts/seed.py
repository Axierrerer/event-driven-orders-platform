"""Тестовые данные локального стенда (идемпотентно): администратор, менеджер,
категории, товары и остатки. Работает через публичный API (Nginx → api-gateway).

    uv run python scripts/seed.py            # обычно вызывается из make dev-up

Пароли — из SEED_ADMIN_PASSWORD / SEED_MANAGER_PASSWORD (по умолчанию — dev-значения).
"""

import os
import subprocess
import sys
import time
from decimal import Decimal
from typing import Any

import httpx

API = os.environ.get("SEED_API_URL", "http://localhost:8000/api/v1")
ADMIN_EMAIL = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "local-dev-admin-passphrase")
MANAGER_EMAIL = "manager@example.com"
MANAGER_PASSWORD = os.environ.get("SEED_MANAGER_PASSWORD", "local-dev-manager-passphrase")
STOCK_PER_PRODUCT = 50

CATALOG: dict[str, list[tuple[str, str, str]]] = {
    "Посуда": [
        ("TEA-POT-01", "Чайник заварочный", "1490.00"),
        ("CUP-01", "Чашка фарфоровая", "390.00"),
        ("PLATE-01", "Тарелка обеденная", "450.00"),
        ("GLASS-01", "Стакан стеклянный", "190.00"),
    ],
    "Текстиль": [
        ("TOWEL-01", "Полотенце махровое", "890.00"),
        ("APRON-01", "Фартук льняной", "1290.00"),
        ("NAPKIN-01", "Салфетки хлопковые, 4 шт.", "690.00"),
        ("BLANKET-01", "Плед шерстяной", "4990.00"),
    ],
    "Кухня": [
        ("KNIFE-01", "Нож поварской", "2790.00"),
        ("BOARD-01", "Доска разделочная", "1190.00"),
        ("PAN-01", "Сковорода чугунная", "3490.00"),
        ("WHISK-01", "Венчик", "350.00"),
    ],
    "Хранение": [
        ("JAR-01", "Банка для круп", "590.00"),
        ("BOX-01", "Контейнер для ланча", "790.00"),
        ("BASKET-01", "Корзина плетёная", "1590.00"),
        ("TIN-01", "Жестяная коробка для чая", "490.00"),
    ],
    "Декор": [
        ("CANDLE-01", "Свеча ароматическая", "990.00"),
        ("VASE-01", "Ваза керамическая", "2190.00"),
        ("FRAME-01", "Рамка для фото", "690.00"),
        ("CLOCK-01", "Часы настенные", "3290.00"),
    ],
}


def log(message: str) -> None:
    print(f"  seed: {message}", flush=True)


def create_user(email: str, password: str) -> None:
    """Пользователь с подтверждённым email через CLI auth-service (идемпотентно)."""
    result = subprocess.run(  # noqa: S603 — фиксированная команда без пользовательского ввода
        [  # noqa: S607
            "docker",
            "compose",
            "exec",
            "-T",
            "-e",
            "NEW_USER_PASSWORD",
            "auth-service",
            "python",
            "-m",
            "src.cli",
            "create-user",
            "--email",
            email,
            "--verified",
        ],
        env={**os.environ, "NEW_USER_PASSWORD": password},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(f"cannot create {email}: {result.stderr.strip() or result.stdout.strip()}")


def login(client: httpx.Client, email: str, password: str) -> dict[str, Any]:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    if response.status_code == 401:
        sys.exit(
            f"login failed for {email}: user exists with another password (set SEED_*_PASSWORD)"
        )
    response.raise_for_status()
    return dict(response.json())


def token_with_role(client: httpx.Client, email: str, password: str, role: str) -> str:
    """Роли приходят асинхронно (user.created → user-service → user.roles-changed)."""
    deadline = time.monotonic() + 60
    while True:
        token = login(client, email, password)["access_token"]
        roles = client.get(f"{API}/users/me", headers=bearer(token))
        if roles.status_code == 200 and role in roles.json()["roles"]:
            return str(login(client, email, password)["access_token"])
        if time.monotonic() > deadline:
            sys.exit(f"{email} did not get {role} in time")
        time.sleep(1)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def wait_for_profile(client: httpx.Client, admin: str, email: str) -> str:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        found = client.get(f"{API}/users", params={"email": email}, headers=bearer(admin)).json()
        if found:
            return str(found[0]["id"])
        time.sleep(1)
    sys.exit(f"profile of {email} did not appear")


def ensure_category(client: httpx.Client, admin: str, name: str) -> str:
    existing = {c["name"]: c["id"] for c in client.get(f"{API}/categories").json()}
    if name in existing:
        return str(existing[name])
    response = client.post(f"{API}/categories", json={"name": name}, headers=bearer(admin))
    response.raise_for_status()
    return str(response.json()["id"])


def ensure_product(
    client: httpx.Client, admin: str, category_id: str, sku: str, name: str, price: str
) -> str:
    body = {
        "sku": sku,
        "name": name,
        "price": str(Decimal(price)),
        "category_id": category_id,
        "is_published": True,
    }
    response = client.post(f"{API}/products", json=body, headers=bearer(admin))
    if response.status_code == 201:
        return str(response.json()["id"])
    if response.status_code != 409:
        response.raise_for_status()
    page = client.get(
        f"{API}/products", params={"category": category_id, "limit": 100}, headers=bearer(admin)
    ).json()
    return str(next(p["id"] for p in page["items"] if p["sku"] == sku))


def ensure_stock(client: httpx.Client, admin: str, product_id: str) -> None:
    url = f"{API}/inventory/stock/{product_id}"
    deadline = time.monotonic() + 60
    while (response := client.get(url, headers=bearer(admin))).status_code == 404:
        if time.monotonic() > deadline:
            sys.exit(f"stock row for {product_id} did not appear (product.changed not consumed?)")
        time.sleep(0.5)
    response.raise_for_status()
    on_hand = response.json()["on_hand"]
    if on_hand < STOCK_PER_PRODUCT:
        client.post(
            f"{url}/adjust",
            json={"delta": STOCK_PER_PRODUCT - on_hand, "reason": "seed"},
            headers=bearer(admin),
        ).raise_for_status()


def main() -> None:
    with httpx.Client(timeout=10) as client:
        create_user(ADMIN_EMAIL, ADMIN_PASSWORD)
        admin = token_with_role(client, ADMIN_EMAIL, ADMIN_PASSWORD, "ROLE_ADMIN")
        log(f"admin {ADMIN_EMAIL}")

        create_user(MANAGER_EMAIL, MANAGER_PASSWORD)
        manager_id = wait_for_profile(client, admin, MANAGER_EMAIL)
        client.put(
            f"{API}/users/{manager_id}/roles",
            json={"roles": ["ROLE_USER", "ROLE_MANAGER"]},
            headers=bearer(admin),
        ).raise_for_status()
        token_with_role(client, MANAGER_EMAIL, MANAGER_PASSWORD, "ROLE_MANAGER")
        log(f"manager {MANAGER_EMAIL}")

        products = 0
        for category, items in CATALOG.items():
            category_id = ensure_category(client, admin, category)
            for sku, name, price in items:
                product_id = ensure_product(client, admin, category_id, sku, name, price)
                ensure_stock(client, admin, product_id)
                products += 1
        log(f"{len(CATALOG)} categories, {products} products, {STOCK_PER_PRODUCT} in stock each")


if __name__ == "__main__":
    main()
