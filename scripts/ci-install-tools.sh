#!/usr/bin/env bash
# Устанавливает CLI-инструменты фиксированных версий в CI (Linux x86_64): ./ci-install-tools.sh trivy gitleaks ...
set -euo pipefail

TRIVY_VERSION=0.75.0
GITLEAKS_VERSION=8.30.1
KUBECONFORM_VERSION=0.8.0
HELM_VERSION=3.19.0
K3D_VERSION=5.9.0
KUBESEAL_VERSION=0.40.0

bin="${BIN_DIR:-/usr/local/bin}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() { curl -fsSL --retry 3 "$1" -o "$tmp/archive"; }

for tool in "$@"; do
    case "$tool" in
        trivy)
            fetch "https://github.com/aquasecurity/trivy/releases/download/v$TRIVY_VERSION/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
            tar -xzf "$tmp/archive" -C "$tmp" trivy ;;
        gitleaks)
            fetch "https://github.com/gitleaks/gitleaks/releases/download/v$GITLEAKS_VERSION/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
            tar -xzf "$tmp/archive" -C "$tmp" gitleaks ;;
        kubeconform)
            fetch "https://github.com/yannh/kubeconform/releases/download/v$KUBECONFORM_VERSION/kubeconform-linux-amd64.tar.gz"
            tar -xzf "$tmp/archive" -C "$tmp" kubeconform ;;
        helm)
            fetch "https://get.helm.sh/helm-v$HELM_VERSION-linux-amd64.tar.gz"
            tar -xzf "$tmp/archive" -C "$tmp" --strip-components=1 linux-amd64/helm ;;
        k3d)
            fetch "https://github.com/k3d-io/k3d/releases/download/v$K3D_VERSION/k3d-linux-amd64"
            mv "$tmp/archive" "$tmp/k3d" ;;
        kubeseal)
            fetch "https://github.com/bitnami-labs/sealed-secrets/releases/download/v$KUBESEAL_VERSION/kubeseal-$KUBESEAL_VERSION-linux-amd64.tar.gz"
            tar -xzf "$tmp/archive" -C "$tmp" kubeseal ;;
        *) echo "unknown tool: $tool" >&2; exit 1 ;;
    esac
    sudo install -m 0755 "$tmp/$tool" "$bin/$tool"
    echo "installed: $tool"
done
