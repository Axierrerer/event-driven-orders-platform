from functools import lru_cache

from platform_lib.settings import ServiceSettings


class Settings(ServiceSettings):
    service_name: str = "inventory-service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
