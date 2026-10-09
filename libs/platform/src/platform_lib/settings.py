from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """Общие настройки сервиса; значения приходят из переменных окружения."""

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str
    environment: str = "local"
    log_level: str = "INFO"


class KafkaSettings(BaseSettings):
    """Подключение к Kafka и Schema Registry (значения по умолчанию — локальный стенд)."""

    model_config = SettingsConfigDict(extra="ignore")

    kafka_bootstrap: str = "localhost:9094"
    schema_registry_url: str = "http://localhost:8081"
