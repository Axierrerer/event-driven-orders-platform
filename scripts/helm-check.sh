#!/usr/bin/env bash
# helm lint + helm template | kubeconform для всех чартов и окружений
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
"$root/scripts/helm-deps.sh"
cd "$root/deploy/helm"
crds='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
for chart in service-lib infra auth-service user-service product-service inventory-service order-service notification-service api-gateway; do
    helm lint --quiet "$chart"
done
helm template infra infra -n orders | kubeconform -strict -summary -schema-location default -
for env in dev prod; do
    helm lint --quiet platform -f "platform/values-$env.yaml"
    helm template platform platform -n orders -f "platform/values-$env.yaml" \
        | kubeconform -strict -summary -schema-location default -schema-location "$crds" -
done
