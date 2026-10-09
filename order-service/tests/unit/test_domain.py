from decimal import Decimal
from itertools import product
from uuid import UUID

import pytest

from events import OrderStatus
from src.domain.models import OrderLine, merge_items, order_total, request_fingerprint
from src.domain.status import Action, InvalidTransitionError, allowed_actions, next_status

pytestmark = pytest.mark.unit

A = UUID("00000000-0000-7000-8000-00000000000a")
B = UUID("00000000-0000-7000-8000-00000000000b")

ALLOWED = {
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


@pytest.mark.parametrize(("status", "action"), list(product(OrderStatus, Action)))
def test_every_status_action_pair(status: OrderStatus, action: Action) -> None:
    expected = ALLOWED.get((status, action))
    if expected is None:
        with pytest.raises(InvalidTransitionError):
            next_status(status, action)
    else:
        assert next_status(status, action) is expected


def test_final_statuses_allow_nothing() -> None:
    assert allowed_actions(OrderStatus.COMPLETED) == set()
    assert allowed_actions(OrderStatus.CANCELLED) == set()


def test_total_is_exact_decimal() -> None:
    lines = [OrderLine(A, "a", Decimal("0.10"), 3), OrderLine(B, "b", Decimal("1499.99"), 2)]
    assert order_total(lines) == Decimal("3000.28")
    assert lines[0].line_total == Decimal("0.30")


def test_merge_items_sums_duplicates() -> None:
    assert merge_items([(A, 1), (B, 2), (A, 3)]) == {A: 4, B: 2}


def test_fingerprint_ignores_item_order() -> None:
    assert request_fingerprint({A: 1, B: 2}) == request_fingerprint({B: 2, A: 1})
    assert request_fingerprint({A: 1}) != request_fingerprint({A: 2})
