from functools import lru_cache

from platform_lib.settings import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "api-gateway"

    # Строки подключения только из окружения: в коде нет паролей
    redis_url: str
    auth_jwks_url: str = "http://auth-service:8001/api/v1/auth/.well-known/jwks.json"

    auth_service_url: str = "http://auth-service:8001"
    user_service_url: str = "http://user-service:8002"
    product_service_url: str = "http://product-service:8003"
    inventory_service_url: str = "http://inventory-service:8004"
    order_service_url: str = "http://order-service:8005"
    notification_service_url: str = "http://notification-service:8006"
    product_grpc_target: str = "product-service:50051"

    upstream_timeout_seconds: float = 5.0
    grpc_timeout_seconds: float = 1.0
    max_body_bytes: int = 1_048_576

    # Rate limit (token bucket): ёмкость = burst, refill — секунд на один токен
    user_rate_capacity: int = 200
    user_rate_refill_seconds: float = 0.01  # 100 rps
    anonymous_rate_capacity: int = 40
    anonymous_rate_refill_seconds: float = 0.05  # 20 rps
    login_rate_capacity: int = 10
    login_rate_refill_seconds: float = 6.0  # 10 в минуту

    openapi_cache_seconds: float = 60.0

    def upstreams(self) -> dict[str, str]:
        return {
            "auth": self.auth_service_url,
            "user": self.user_service_url,
            "product": self.product_service_url,
            "inventory": self.inventory_service_url,
            "order": self.order_service_url,
            "notification": self.notification_service_url,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
