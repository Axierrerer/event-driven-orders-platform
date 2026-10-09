from functools import lru_cache

from platform_lib.settings import KafkaSettings, ServiceSettings


class Settings(ServiceSettings, KafkaSettings):
    service_name: str = "order-service"

    # Строки подключения только из окружения: в коде нет паролей
    database_url: str
    auth_jwks_url: str = "http://auth-service:8001/api/v1/auth/.well-known/jwks.json"

    product_grpc_target: str = "product-service:50051"
    inventory_grpc_target: str = "inventory-service:50052"
    catalog_timeout_seconds: float = 1.0
    inventory_timeout_seconds: float = 0.3

    idempotency_key_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
