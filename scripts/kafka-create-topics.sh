#!/bin/sh
# Идемпотентно создаёт топики событий и их DLQ.
set -eu

BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9092}"
PARTITIONS="${KAFKA_TOPIC_PARTITIONS:-3}"
RETENTION_MS=604800000  # 7 дней

TOPICS="
user.created
user.verification-requested
user.roles-changed
product.changed
order.created
inventory.reserved
inventory.reservation-failed
inventory.released
order.status-changed
"

for topic in $TOPICS; do
    for name in "$topic" "$topic.dlq"; do
        /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" \
            --create --if-not-exists --topic "$name" \
            --partitions "$PARTITIONS" --replication-factor 1 \
            --config retention.ms="$RETENTION_MS" >/dev/null
        echo "topic ok: $name"
    done
done
