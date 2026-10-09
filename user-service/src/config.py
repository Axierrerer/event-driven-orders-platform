from functools import lru_cache

from platform_lib.settings import KafkaSettings, ServiceSettings


class Settings(ServiceSettings, KafkaSettings):
    service_name: str = "user-service"

    # Строки подключения только из окружения: в коде нет паролей
    database_url: str
    auth_jwks_url: str = "http://auth-service:8001/api/v1/auth/.well-known/jwks.json"

    # Пользователь с этим email при создании сразу получает ROLE_ADMIN (первый администратор)
    bootstrap_admin_email: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
