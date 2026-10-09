# Stop and delete every qb-integration container, network and named volume.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
docker compose -p qb-integration -f docker/docker-compose.integration.yml --profile extended down -v --remove-orphans
