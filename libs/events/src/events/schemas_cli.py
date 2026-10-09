"""Управление JSON Schema событий.

python -m events.schemas_cli export              # записать схемы в libs/events/schemas
python -m events.schemas_cli check               # схемы в репозитории совпадают с моделями
python -m events.schemas_cli register --url URL  # зарегистрировать (идемпотентно)
python -m events.schemas_cli compat --url URL    # проверить совместимость с реестром
"""

import argparse
import json
import sys
from pathlib import Path

from confluent_kafka.schema_registry import Schema, SchemaRegistryClient

from events.base import schema_document
from events.models import EVENTS_BY_TOPIC
from events.serde import subject_name

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"
COMPATIBILITY = "BACKWARD"


def render(topic: str) -> str:
    document = schema_document(EVENTS_BY_TOPIC[topic])
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def export(schemas_dir: Path) -> None:
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for topic in EVENTS_BY_TOPIC:
        (schemas_dir / f"{topic}.json").write_text(render(topic))
        print(f"exported: {topic}")


def check(schemas_dir: Path) -> int:
    stale = [
        topic
        for topic in EVENTS_BY_TOPIC
        if not (path := schemas_dir / f"{topic}.json").exists() or path.read_text() != render(topic)
    ]
    for topic in stale:
        print(f"stale schema: {topic}", file=sys.stderr)
    return 1 if stale else 0


def _schema(topic: str) -> Schema:
    return Schema(json.dumps(schema_document(EVENTS_BY_TOPIC[topic])), "JSON")


def register(client: SchemaRegistryClient) -> None:
    for topic in EVENTS_BY_TOPIC:
        subject = subject_name(topic)
        client.set_compatibility(subject, COMPATIBILITY)
        schema_id = client.register_schema(subject, _schema(topic), normalize_schemas=True)
        print(f"registered: {subject} (id={schema_id})")


def compat(client: SchemaRegistryClient) -> int:
    existing = set(client.get_subjects())
    incompatible = []
    for topic in EVENTS_BY_TOPIC:
        subject = subject_name(topic)
        if subject not in existing:
            print(f"new subject: {subject}")
            continue
        if client.test_compatibility(subject, _schema(topic)):
            print(f"compatible: {subject}")
        else:
            incompatible.append(subject)
            print(f"INCOMPATIBLE: {subject}", file=sys.stderr)
    return 1 if incompatible else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="events.schemas_cli")
    parser.add_argument("command", choices=["export", "check", "register", "compat"])
    parser.add_argument("--url", default="http://localhost:8081", help="URL Schema Registry")
    parser.add_argument("--dir", type=Path, default=SCHEMAS_DIR, help="каталог схем")
    args = parser.parse_args(argv)

    if args.command == "export":
        export(args.dir)
        return 0
    if args.command == "check":
        return check(args.dir)
    client = SchemaRegistryClient({"url": args.url})
    if args.command == "register":
        register(client)
        return 0
    return compat(client)


if __name__ == "__main__":
    sys.exit(main())
