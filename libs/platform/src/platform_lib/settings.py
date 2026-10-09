from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    """Общие настройки сервиса; значения приходят из переменных окружения."""

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str
    environment: str = "local"
    log_level: str = "INFO"
    # OTLP gRPC (например, http://otel-collector:4317); пусто — трейсы не экспортируются
    otel_exporter_otlp_endpoint: str | None = None
    worker_metrics_port: int = 9100


class KafkaSettings(BaseSettings):
    """Подключение к Kafka и Schema Registry (значения по умолчанию — локальный стенд)."""

    model_config = SettingsConfigDict(extra="ignore")

    kafka_bootstrap: str = "localhost:9094"
    schema_registry_url: str = "http://localhost:8081"
