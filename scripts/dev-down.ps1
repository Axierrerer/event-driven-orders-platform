# Остановить локальный стенд (аналог `make dev-down`), данные сохраняются.
$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

docker compose down
exit $LASTEXITCODE
