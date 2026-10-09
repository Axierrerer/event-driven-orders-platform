#!/usr/bin/env bash
# Локальный Kubernetes: кластер k3d → cert-manager, sealed-secrets → образы в registry →
# секреты → инфраструктура → сервисы. Повторный запуск обновляет то, что уже есть.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

cluster="${CLUSTER:-orders}"
namespace="${NAMESPACE:-orders}"
values="${VALUES:-deploy/helm/platform/values-dev.yaml}"
registry_port="${REGISTRY_PORT:-5050}"   # 5000 на macOS занят AirPlay
registry="k3d-registry.localhost:$registry_port"
tag="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
services="auth-service user-service product-service inventory-service order-service notification-service api-gateway"

step() { printf '\n== %s\n' "$1"; }

step "Кластер k3d '$cluster' (1 server + 2 agents, registry $registry)"
if ! k3d cluster list "$cluster" >/dev/null 2>&1; then
    k3d cluster create "$cluster" --servers 1 --agents 2 \
        --registry-create "k3d-registry.localhost:0.0.0.0:$registry_port" \
        -p "443:443@loadbalancer" -p "80:80@loadbalancer" --wait
fi
kubectl config use-context "k3d-$cluster" >/dev/null

step "cert-manager и sealed-secrets"
helm repo add jetstack https://charts.jetstack.io --force-update >/dev/null
helm upgrade --install cert-manager jetstack/cert-manager --version v1.18.2 \
    --namespace cert-manager --create-namespace --set crds.enabled=true --wait
# Официальный манифест контроллера (kube-system/sealed-secrets-controller — имя по умолчанию kubeseal)
kubectl apply -f "https://github.com/bitnami-labs/sealed-secrets/releases/download/v${SEALED_SECRETS_VERSION:-0.40.0}/controller.yaml" >/dev/null
kubectl rollout status deploy/sealed-secrets-controller -n kube-system --timeout=300s

step "Образы сервисов → $registry (тег $tag)"
# PULL_REGISTRY=ghcr.io/<owner> — взять готовые образы (CD), иначе собрать локально
if [ -n "${PULL_REGISTRY:-}" ]; then
    for service in $services; do
        docker pull -q "$PULL_REGISTRY/orders-platform-$service:$tag" >/dev/null
        docker tag "$PULL_REGISTRY/orders-platform-$service:$tag" "orders-platform-$service"
    done
else
    docker compose build $services schema-init >/dev/null
fi
for service in $services; do
    docker tag "orders-platform-$service" "localhost:$registry_port/orders-platform-$service:$tag"
    docker push -q "localhost:$registry_port/orders-platform-$service:$tag" >/dev/null
    echo "  pushed: orders-platform-$service:$tag"
done

step "Секреты (SealedSecret)"
NAMESPACE="$namespace" ./scripts/inject-secrets.sh

step "Инфраструктура"
kubectl create configmap infra-scripts -n "$namespace" \
    --from-file=scripts/postgres-init-databases.sh --from-file=scripts/kafka-create-topics.sh \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
helm upgrade --install infra deploy/helm/infra -n "$namespace" --wait --timeout 10m

step "Сервисы платформы"
./scripts/helm-deps.sh
helm upgrade --install platform deploy/helm/platform -n "$namespace" -f "$values" \
    --set global.image.tag="$tag" --wait --timeout 10m

step "Готово"
kubectl get pods -n "$namespace"
echo
echo "API: https://api.orders.localhost (curl -k https://api.orders.localhost/health/ready)"
