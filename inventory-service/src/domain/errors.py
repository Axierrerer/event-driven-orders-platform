class InventoryError(Exception):
    pass


class StockNotFoundError(InventoryError):
    pass


class InvalidAdjustmentError(InventoryError):
    """Корректировка сделала бы остаток отрицательным или меньше зарезервированного."""
