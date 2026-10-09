# Поднять локальный стенд (аналог `make dev-up` для PowerShell 5+).
$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)

docker compose up -d --build --wait
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Стенд поднят:"
Write-Host "  API gateway / Swagger: http://localhost:8000/docs"
Write-Host "  Mailpit:               http://localhost:8025"
Write-Host "  Schema Registry:       http://localhost:8081"
Write-Host "  Kafka (с хоста):       localhost:9094"
