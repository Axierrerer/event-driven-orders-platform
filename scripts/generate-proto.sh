#!/usr/bin/env bash
# Генерирует Python-код gRPC из proto/ в libs/proto/src (или в каталог из $1).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$root/libs/proto/src}"

mkdir -p "$out"
find "$root/proto" -name '*.proto' -print0 | xargs -0 uv run --directory "$root" python -m grpc_tools.protoc \
    --proto_path="$root/proto" \
    --python_out="$out" \
    --pyi_out="$out" \
    --grpc_python_out="$out"

# Пакеты Python для каждого уровня каталогов
find "$out/orders_proto" -type d -exec sh -c 'test -f "$1/__init__.py" || : > "$1/__init__.py"' _ {} \;

# Пакет типизирован (*.pyi генерирует protoc)
: > "$out/orders_proto/py.typed"
