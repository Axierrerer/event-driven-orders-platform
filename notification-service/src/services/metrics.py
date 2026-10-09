from prometheus_client import Counter

NOTIFICATIONS = Counter("notifications_total", "Email delivery outcomes", ["template", "result"])
