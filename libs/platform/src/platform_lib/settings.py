from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """Общие настройки сервиса; значения приходят из переменных окружения."""

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str
    environment: str = "local"
    log_level: str = "INFO"
