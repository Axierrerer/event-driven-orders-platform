from prometheus_client import Counter, Gauge, Histogram

ORDERS_CREATED = Counter("orders_created_total", "Orders placed")
ORDER_TRANSITIONS = Counter(
    "order_status_transitions_total", "Order status changes", ["to_status", "actor"]
)
SAGA_RESERVATION_SECONDS = Histogram(
    "saga_reservation_duration_seconds",
    "Time from order creation to the inventory decision (reserved or cancelled)",
    ["outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
ORDERS_STUCK_NEW = Gauge(
    "orders_stuck_new", "Orders still NEW longer than the saga threshold (2 minutes)"
)
