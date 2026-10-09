from prometheus_client import Counter

RESERVATIONS = Counter("reservations_total", "Reservation attempts for orders", ["result"])
RESERVATIONS_RELEASED = Counter("reservations_released_total", "Released reservations", ["reason"])
