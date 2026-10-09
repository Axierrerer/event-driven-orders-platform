from functools import lru_cache

from platform_lib.settings import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "user-service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
