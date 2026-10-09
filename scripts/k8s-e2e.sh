#!/usr/bin/env bash
# Сквозные сценарии против платформы в кластере (локальный k3d или CD).
# На время прогона: короткий срок резерва и высокие лимиты gateway; потом — значения из values.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
namespace="${NAMESPACE:-orders}"
values="${VALUES:-deploy/helm/platform/values-dev.yaml}"
host="https://api.orders.localhost"
mailpit_port="${MAILPIT_LOCAL_PORT:-18025}"
tag="$(helm get values platform -n "$namespace" -a -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["global"]["image"]["tag"])')"
e2e_values=(
    --set inventory-service.env.RESERVATION_TTL_SECONDS=15
    --set api-gateway.env.ANONYMOUS_RATE_CAPACITY=100000
    --set api-gateway.env.USER_RATE_CAPACITY=100000
    --set api-gateway.env.LOGIN_RATE_CAPACITY=100000
)

restore() {
    if [ -n "${forward_pid:-}" ]; then kill "$forward_pid" 2>/dev/null; wait "$forward_pid" 2>/dev/null || true; fi
    helm upgrade platform "$root/deploy/helm/platform" -n "$namespace" -f "$root/$values" \
        --set global.image.tag="$tag" --wait --timeout 10m >/dev/null
}
trap restore EXIT

helm upgrade platform deploy/helm/platform -n "$namespace" -f "$values" --reuse-values \
    "${e2e_values[@]}" --wait --timeout 10m >/dev/null
SEED_TARGET=k8s SEED_TLS_VERIFY=0 SEED_API_URL="$host/api/v1" NAMESPACE="$namespace" \
    uv run python scripts/seed.py

# Письма с токенами подтверждения читаются из Mailpit
kubectl port-forward -n "$namespace" svc/mailpit "$mailpit_port:8025" >/dev/null 2>&1 &
forward_pid=$!
for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:$mailpit_port/readyz" >/dev/null 2>&1 && break
    sleep 1
done

cd e2e
E2E_TARGET=k8s E2E_NAMESPACE="$namespace" E2E_TLS_VERIFY=0 E2E_API_URL="$host/api/v1" \
    E2E_MAILPIT_URL="http://127.0.0.1:$mailpit_port" uv run pytest -q "$@"
