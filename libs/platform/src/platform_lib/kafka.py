"""Фабрики клиентов Kafka с безопасными настройками по умолчанию."""

from confluent_kafka import Consumer, Producer


def make_producer(bootstrap: str, client_id: str) -> Producer:
    """Идемпотентный producer: acks=all, без дублей при ретраях внутри сессии."""
    return Producer(
        {
            "bootstrap.servers": bootstrap,
            "client.id": client_id,
            "acks": "all",
            "enable.idempotence": True,
            "linger.ms": 5,
            "delivery.timeout.ms": 30_000,
        }
    )


def make_consumer(bootstrap: str, group_id: str, client_id: str) -> Consumer:
    """Consumer без автокоммита: offset коммитится только после обработки сообщения."""
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "client.id": client_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "partition.assignment.strategy": "cooperative-sticky",
        }
    )
