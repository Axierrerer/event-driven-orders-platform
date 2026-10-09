"""Конечный автомат статусов заказа — чистые функции без I/O."""

from enum import StrEnum

from events import OrderStatus


class Action(StrEnum):
    """Что меняет статус: событие саги или действие пользователя."""

    RESERVE = "reserve"  # inventory.reserved
    RESERVATION_FAILED = "reservation_failed"  # inventory.reservation-failed
    RESERVATION_EXPIRED = "reservation_expired"  # inventory.released(EXPIRED)
    PAY = "pay"
    CANCEL = "cancel"
    SHIP = "ship"
    COMPLETE = "complete"


_TRANSITIONS: dict[tuple[OrderStatus, Action], OrderStatus] = {
    (OrderStatus.NEW, Action.RESERVE): OrderStatus.RESERVED,
    (OrderStatus.NEW, Action.RESERVATION_FAILED): OrderStatus.CANCELLED,
    (OrderStatus.NEW, Action.CANCEL): OrderStatus.CANCELLED,
    (OrderStatus.RESERVED, Action.CANCEL): OrderStatus.CANCELLED,
    (OrderStatus.RESERVED, Action.RESERVATION_EXPIRED): OrderStatus.CANCELLED,
    (OrderStatus.RESERVED, Action.PAY): OrderStatus.PAID,
    (OrderStatus.PAID, Action.SHIP): OrderStatus.SHIPPED,
    (OrderStatus.PAID, Action.CANCEL): OrderStatus.CANCELLED,
    (OrderStatus.SHIPPED, Action.COMPLETE): OrderStatus.COMPLETED,
}

FINAL_STATUSES = frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED})


class InvalidTransitionError(Exception):
    def __init__(self, status: OrderStatus, action: Action) -> None:
        super().__init__(f"cannot {action} an order in status {status}")
        self.status = status
        self.action = action


def next_status(current: OrderStatus, action: Action) -> OrderStatus:
    """Новый статус или InvalidTransitionError, если действие в этом статусе запрещено."""
    try:
        return _TRANSITIONS[(current, action)]
    except KeyError:
        raise InvalidTransitionError(current, action) from None


def allowed_actions(current: OrderStatus) -> set[Action]:
    return {action for (status, action) in _TRANSITIONS if status is current}
