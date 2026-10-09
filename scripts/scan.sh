#!/usr/bin/env bash
# Проверки безопасности: зависимости, секреты, конфигурация, образы.
# Падает на CRITICAL; HIGH — печатается для разбора (обоснования в docs/security/).
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
failed=0
step() { printf '\n== %s\n' "$1"; }

step "pip-audit: Python-зависимости всех сервисов"
req="$(mktemp)"
uv export --all-packages --no-dev --no-hashes --no-emit-workspace --format requirements-txt --locked > "$req"
uvx pip-audit --requirement "$req" --disable-pip --no-deps --strict --progress-spinner off || failed=1
rm -f "$req"

step "gitleaks: секреты в истории git"
gitleaks git --no-banner --redact --config .gitleaks.toml . || failed=1

step "trivy config: Dockerfile и манифесты"
trivy config --quiet --severity HIGH,CRITICAL --exit-code 0 . 
trivy config --quiet --severity CRITICAL --exit-code 1 . >/dev/null || failed=1

step "trivy image: любой CRITICAL или HIGH с доступным исправлением — ошибка"
for service in auth-service user-service product-service inventory-service order-service notification-service api-gateway; do
    image="orders-platform-${service}"
    if ! docker image inspect "$image" >/dev/null 2>&1; then
        echo "  $image: образ не собран (make dev-up)"; failed=1; continue
    fi
    critical=$(trivy image --quiet --severity CRITICAL --format json "$image" 2>/dev/null \
        | python3 -c 'import json,sys; print(sum(len(r.get("Vulnerabilities") or []) for r in json.load(sys.stdin).get("Results", [])))')
    fixable_high=$(trivy image --quiet --ignore-unfixed --severity HIGH --format json "$image" 2>/dev/null \
        | python3 -c 'import json,sys; print(sum(len(r.get("Vulnerabilities") or []) for r in json.load(sys.stdin).get("Results", [])))')
    printf '  %-36s critical=%s fixable_high=%s\n' "$image" "$critical" "$fixable_high"
    if [ "$critical" != "0" ] || [ "$fixable_high" != "0" ]; then failed=1; fi
done
echo "  (HIGH без исправления в базовом образе — docs/security/exceptions.md)"

if [ "$failed" -ne 0 ]; then
    echo; echo "Проверки безопасности не пройдены"; exit 1
fi
echo; echo "Проверки безопасности пройдены"
