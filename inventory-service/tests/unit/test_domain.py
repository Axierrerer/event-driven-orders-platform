from uuid import UUID

import pytest

from src.domain.models import Shortage, StockLevel, find_shortages, merge_quantities

pytestmark = pytest.mark.unit

A = UUID("00000000-0000-7000-8000-00000000000a")
B = UUID("00000000-0000-7000-8000-00000000000b")
C = UUID("00000000-0000-7000-8000-00000000000c")


def test_merge_quantities_sums_duplicates_and_sorts() -> None:
    merged = merge_quantities([(B, 1), (A, 2), (B, 3)])
    assert merged == {A: 2, B: 4}
    assert list(merged) == [A, B]


def test_find_shortages() -> None:
    stock = {A: StockLevel(A, on_hand=5, reserved=3), B: StockLevel(B, on_hand=10, reserved=0)}
    unknown, shortages = find_shortages({A: 3, B: 10, C: 1}, stock)
    assert unknown == [C]
    assert shortages == [Shortage(A, requested=3, available=2)]


def test_no_shortages_when_everything_available() -> None:
    stock = {A: StockLevel(A, on_hand=5, reserved=0)}
    assert find_shortages({A: 5}, stock) == ([], [])
