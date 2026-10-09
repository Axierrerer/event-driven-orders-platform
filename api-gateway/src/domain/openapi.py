"""Слияние OpenAPI-схем сервисов в одну для /docs gateway."""

import copy
import json
from collections.abc import Mapping
from typing import Any

INTERNAL_PATH_PREFIXES = ("/health",)


def merge_openapi(
    specs: Mapping[str, dict[str, Any]], *, title: str, version: str
) -> dict[str, Any]:
    """Объединяет paths и components.schemas. Одноимённые схемы с разным содержимым
    переименовываются в `<service>_<Name>`, ссылки на них в путях сервиса обновляются."""
    merged: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "paths": {},
        "components": {
            "schemas": {},
            "securitySchemes": {"HTTPBearer": {"type": "http", "scheme": "bearer"}},
        },
        "tags": [],
    }
    schemas: dict[str, Any] = merged["components"]["schemas"]
    seen_tags: set[str] = set()

    for service, original in specs.items():
        spec = copy.deepcopy(original)
        service_schemas = spec.get("components", {}).get("schemas", {})
        renames = {
            name: f"{service}_{name}"
            for name, schema in service_schemas.items()
            if name in schemas and schemas[name] != schema
        }
        if renames:
            text = json.dumps(spec)
            for old, new in renames.items():
                text = text.replace(
                    f'"#/components/schemas/{old}"', f'"#/components/schemas/{new}"'
                )
            spec = json.loads(text)
            service_schemas = {
                renames.get(name, name): schema
                for name, schema in spec.get("components", {}).get("schemas", {}).items()
            }
        for name, schema in service_schemas.items():
            schemas.setdefault(name, schema)
        for path, item in spec.get("paths", {}).items():
            if not path.startswith(INTERNAL_PATH_PREFIXES):
                merged["paths"][path] = item
        for tag in spec.get("tags", []):
            if tag.get("name") not in seen_tags:
                seen_tags.add(tag["name"])
                merged["tags"].append(tag)
    return merged
