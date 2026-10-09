from functools import lru_cache

from platform_lib.settings import KafkaSettings, ServiceSettings


class Settings(ServiceSettings, KafkaSettings):
    service_name: str = "product-service"

    # Строки подключения только из окружения: в коде нет паролей
    mongo_url: str
    redis_url: str
    mongo_db: str = "catalog"
    auth_jwks_url: str = "http://auth-service:8001/api/v1/auth/.well-known/jwks.json"

    grpc_port: int = 50051
    product_cache_ttl_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
