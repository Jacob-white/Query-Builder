# Start the live-integration services (compose project "qb-integration").
#   scripts\it_up.ps1              required tier  (PostgreSQL, MySQL, MariaDB, ClickHouse)
#   scripts\it_up.ps1 -Extended    + SQL Server, CockroachDB, TimescaleDB, Trino, QuestDB,
#                                    MongoDB, Redis Stack, Elasticsearch, OpenSearch, Neo4j, Cassandra
# SQLite and DuckDB are in-process and need no service.
# Only containers of the qb-integration project are created; nothing else is touched.
param([switch]$Extended)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$profileArgs = @()
if ($Extended) { $profileArgs = @('--profile', 'extended') }
docker compose -p qb-integration -f docker/docker-compose.integration.yml @profileArgs up -d --wait
