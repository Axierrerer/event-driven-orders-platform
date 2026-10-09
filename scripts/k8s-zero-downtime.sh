#!/usr/bin/env bash
# Проверка обновления без простоя: под нагрузкой (~50 RPS через ingress)
# order-service масштабируется до 4 реплик, затем вся платформа обновляется на новый тег образа.
# Результат: число ответов 5xx за прогон (ожидается 0).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
namespace="${NAMESPACE:-orders}"
values="${VALUES:-deploy/helm/platform/values-dev.yaml}"
registry_port="${REGISTRY_PORT:-5050}"
host="https://api.orders.localhost"
reports="load/reports"
services="auth-service user-service product-service inventory-service order-service notification-service api-gateway"
old_tag="$(helm get values platform -n "$namespace" -a -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["global"]["image"]["tag"])')"
new_tag="${old_tag%-r*}-r$(date +%s)"
# На время проверки лимиты gateway выше нагрузки (все запросы идут с одного IP)
limits=(--set api-gateway.env.ANONYMOUS_RATE_CAPACITY=1000000 --set api-gateway.env.USER_RATE_CAPACITY=1000000)

step() { printf '\n== %s\n' "$1"; }

step "Тестовые данные и лимиты gateway"
helm upgrade platform deploy/helm/platform -n "$namespace" -f "$values" --reuse-values "${limits[@]}" --wait >/dev/null
SEED_TARGET=k8s SEED_TLS_VERIFY=0 SEED_API_URL="$host/api/v1" uv run python scripts/seed.py

step "Новый тег образов: $new_tag"
for service in $services; do
    docker tag "localhost:$registry_port/orders-platform-$service:$old_tag" "localhost:$registry_port/orders-platform-$service:$new_tag"
    docker push -q "localhost:$registry_port/orders-platform-$service:$new_tag" >/dev/null
done

step "Нагрузка 50 RPS (3 минуты)"
mkdir -p "$reports"
LOAD_TLS_VERIFY=0 LOAD_RPS_PER_USER=5 uv run locust -f load/locustfile.py --headless --host "$host" \
    -u 10 -r 10 -t 180s --csv "$reports/k8s" --only-summary > "$reports/k8s.log" 2>&1 &
locust_pid=$!
sleep 30

step "kubectl scale order-service --replicas=4"
kubectl scale deploy/order-service -n "$namespace" --replicas=4
kubectl rollout status deploy/order-service -n "$namespace" --timeout=300s

step "helm upgrade на $new_tag"
helm upgrade platform deploy/helm/platform -n "$namespace" -f "$values" --reuse-values "${limits[@]}" \
    --set global.image.tag="$new_tag" --wait --timeout 10m >/dev/null
kubectl get deploy -n "$namespace" -o 'custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,IMAGE:.spec.template.spec.containers[0].image' \
    | grep -E "NAME|order-service|api-gateway"

wait "$locust_pid" || true

step "Результат"
status=0
python3 - "$reports/k8s_stats.csv" "$reports/k8s_failures.csv" <<'PY' || status=$?
import csv, re, sys
stats = {row["Name"]: row for row in csv.DictReader(open(sys.argv[1]))}
total = stats["Aggregated"]
errors_5xx = sum(
    int(row["Occurrences"]) for row in csv.DictReader(open(sys.argv[2]))
    if re.search(r"\b5\d\d\b", row["Error"])
)
print(f"запросов: {total['Request Count']}, RPS: {float(total['Requests/s']):.1f}, "
      f"ошибок: {total['Failure Count']}, из них 5xx: {errors_5xx}")
sys.exit(1 if errors_5xx else 0)
PY

step "Возврат лимитов gateway"
helm upgrade platform deploy/helm/platform -n "$namespace" -f "$values" --set global.image.tag="$new_tag" --wait >/dev/null
exit $status
