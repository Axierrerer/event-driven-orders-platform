#!/usr/bin/env bash
# Шифрует локальные секреты в SealedSecret и применяет их в кластер.
#   <dir>/<name>.env  → Secret <name> (каждая строка KEY=VALUE — ключ)
#   <dir>/<name>/     → Secret <name> (каждый файл — ключ; README.md пропускается)
# Открытые значения в кластер не попадают: kubectl create --dry-run → kubeseal → apply.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
dir="${SECRETS_DIR:-$root/.secrets/dev}"
example="$root/.secrets.example/dev"
namespace="${NAMESPACE:-orders}"
controller="${SEALED_SECRETS_CONTROLLER:-sealed-secrets-controller}"

if [ ! -d "$dir" ]; then
    echo "Нет $dir — создаю из .secrets.example/dev со случайными паролями"
    mkdir -p "$dir"
    cp -R "$example/." "$dir/"
    # change-me-* → случайные значения; файл видит только владелец
    for env_file in "$dir"/*.env; do
        tmp="$(mktemp)"
        while IFS= read -r line; do
            case "$line" in
                *=change-me-*) printf '%s=%s\n' "${line%%=*}" "$(openssl rand -hex 24)" ;;
                *) printf '%s\n' "$line" ;;
            esac
        done < "$env_file" > "$tmp"
        mv "$tmp" "$env_file"
    done
    chmod -R go-rwx "$dir"
fi

key="$dir/auth-jwt-key/jwt.pem"
if [ ! -f "$key" ]; then
    mkdir -p "$(dirname "$key")"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$key" 2>/dev/null
    chmod 600 "$key"
    echo "Создан новый ключ подписи JWT"
fi

kubectl get namespace "$namespace" >/dev/null 2>&1 || kubectl create namespace "$namespace" >/dev/null

seal() {
    local name="$1"; shift
    kubectl create secret generic "$name" --namespace "$namespace" "$@" --dry-run=client -o yaml \
        | kubeseal --controller-name "$controller" --controller-namespace kube-system --format yaml \
        | kubectl apply -f - >/dev/null
    echo "  sealed: $namespace/$name"
}

shopt -s nullglob
for env_file in "$dir"/*.env; do
    seal "$(basename "$env_file" .env)" --from-env-file "$env_file"
done
for secret_dir in "$dir"/*/; do
    args=()
    for file in "$secret_dir"*; do
        [ -f "$file" ] && [ "$(basename "$file")" != README.md ] && args+=(--from-file "$file")
    done
    [ ${#args[@]} -gt 0 ] && seal "$(basename "$secret_dir")" "${args[@]}"
done

# Контроллер расшифровывает асинхронно — ждём появления Secret'ов
for env_file in "$dir"/*.env "$dir"/*/; do
    name="$(basename "${env_file%/}" .env)"
    for _ in $(seq 1 30); do
        kubectl get secret "$name" -n "$namespace" >/dev/null 2>&1 && break
        sleep 1
    done
done
