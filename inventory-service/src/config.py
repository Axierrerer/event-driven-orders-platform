from functools import lru_cache

from platform_lib.settings import KafkaSettings, ServiceSettings


class Settings(ServiceSettings, KafkaSettings):
    service_name: str = "inventory-service"

    # Строки подключения только из окружения: в коде нет паролей
    database_url: str
    redis_url: str
    auth_jwks_url: str = "http://auth-service:8001/api/v1/auth/.well-known/jwks.json"

    grpc_port: int = 50052
    reservation_ttl_seconds: int = 900
    expiry_check_interval_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
