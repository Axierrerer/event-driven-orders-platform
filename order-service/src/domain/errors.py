from uuid import UUID


class OrderError(Exception):
    pass


class OrderNotFoundError(OrderError):
    pass


class EmailNotVerifiedError(OrderError):
    pass


class ForbiddenActionError(OrderError):
    """Роль пользователя не позволяет это действие (статус при этом допустим)."""


class InvalidOrderError(OrderError):
    """Состав заказа некорректен: лимиты, неизвестные или скрытые товары, разные валюты."""

    def __init__(self, message: str, product_ids: list[UUID] | None = None) -> None:
        super().__init__(message)
        self.product_ids = product_ids or []


class OutOfStockError(OrderError):
    def __init__(self, details: list[tuple[UUID, int, int]]) -> None:
        super().__init__("not enough stock")
        self.details = details  # (product_id, requested, available)


class IdempotencyConflictError(OrderError):
    """Тот же Idempotency-Key уже использован с другим телом запроса."""


class PaymentDeclinedError(OrderError):
    pass


class DependencyUnavailableError(OrderError):
    """Каталог недоступен — без цен заказ создать нельзя."""
