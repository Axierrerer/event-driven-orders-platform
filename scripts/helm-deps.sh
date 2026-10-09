#!/usr/bin/env bash
# Собирает зависимости чартов: service-lib → чарты сервисов → platform
set -euo pipefail
cd "$(dirname "$0")/../deploy/helm"
for chart in auth-service user-service product-service inventory-service order-service notification-service api-gateway platform; do
    helm dependency build "$chart" >/dev/null
done
