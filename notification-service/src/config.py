from functools import lru_cache

from platform_lib.settings import KafkaSettings, ServiceSettings


class Settings(ServiceSettings, KafkaSettings):
    service_name: str = "notification-service"

    # Строки подключения только из окружения: в коде нет паролей
    mongo_url: str
    redis_url: str
    mongo_db: str = "notifications"
    auth_jwks_url: str = "http://auth-service:8001/api/v1/auth/.well-known/jwks.json"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "Orders Platform <no-reply@orders.local>"
    smtp_timeout_seconds: float = 10.0

    # Rate limit: token bucket на пользователя и отдельный — на письма подтверждения
    user_bucket_capacity: int = 10
    user_bucket_refill_seconds: float = 60.0
    verification_bucket_capacity: int = 3
    verification_bucket_refill_seconds: float = 1200.0

    dispatch_interval_seconds: float = 1.0
    max_send_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
