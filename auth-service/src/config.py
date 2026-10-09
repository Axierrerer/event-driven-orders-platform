from functools import lru_cache
from pathlib import Path

from platform_lib.settings import KafkaSettings, ServiceSettings


class Settings(ServiceSettings, KafkaSettings):
    service_name: str = "auth-service"

    # Строки подключения только из окружения: в коде нет паролей
    database_url: str
    redis_url: str

    # Ключ подписи JWT (RS256). В локальном окружении создаётся автоматически, если файла нет.
    jwt_private_key_path: Path = Path("/var/lib/auth/keys/jwt.pem")
    jwt_key_id: str = "auth-1"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30

    email_verification_ttl_hours: int = 24
    app_base_url: str = "http://localhost:8000"

    login_max_failures: int = 5
    login_failure_window_seconds: int = 900

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
