#!/usr/bin/env bash
# Проверка окружения разработчика.
# Код выхода 0 — всё установлено; иначе печатает, чего не хватает.
set -u

missing=0

check() {
    local name="$1" version_cmd="$2"
    if command -v "$name" >/dev/null 2>&1; then
        printf "  %-10s %s\n" "$name" "$(eval "$version_cmd" 2>&1 | head -1)"
    else
        printf "  %-10s НЕ НАЙДЕН\n" "$name"
        missing=1
    fi
}

echo "Инструменты:"
check uv       "uv --version"
check docker   "docker --version"
check make     "make --version"
check git      "git --version"
check k3d      "k3d version"
check kubectl  "kubectl version --client"
check helm     "helm version --short"
check kubeseal "kubeseal --version"
check trivy    "trivy --version"
check grpcurl  "grpcurl --version"

echo "Python 3.12 (uv):"
if uv python find 3.12 >/dev/null 2>&1; then
    echo "  $(uv python find 3.12)"
else
    echo "  НЕ НАЙДЕН — выполните: uv python install 3.12"
    missing=1
fi

echo "Docker daemon:"
if docker info >/dev/null 2>&1; then
    echo "  запущен"
else
    echo "  НЕ ЗАПУЩЕН — запустите Docker Desktop / OrbStack / Colima"
    missing=1
fi

if docker compose version >/dev/null 2>&1; then
    echo "Docker Compose: $(docker compose version --short)"
else
    echo "Docker Compose v2: НЕ НАЙДЕН"
    missing=1
fi

if [ "$missing" -ne 0 ]; then
    echo "Окружение неполное — установите недостающие инструменты"
    exit 1
fi
echo "Окружение готово."
