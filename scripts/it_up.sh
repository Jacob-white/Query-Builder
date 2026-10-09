#!/usr/bin/env sh
# Start the live-integration services (compose project "qb-integration").
#   scripts/it_up.sh              required tier  (PostgreSQL, MySQL, MariaDB, ClickHouse)
#   scripts/it_up.sh extended     + SQL Server, CockroachDB, TimescaleDB, Trino, QuestDB,
#                                   MongoDB, Redis Stack, Elasticsearch, OpenSearch, Neo4j, Cassandra
# SQLite and DuckDB are in-process and need no service.
# Only containers of the qb-integration project are created; nothing else is touched.
set -eu
cd "$(dirname "$0")/.."
if [ "${1:-}" = "extended" ]; then
  set -- --profile extended
else
  set --
fi
exec docker compose -p qb-integration -f docker/docker-compose.integration.yml "$@" up -d --wait
