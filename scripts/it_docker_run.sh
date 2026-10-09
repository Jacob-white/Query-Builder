#!/usr/bin/env sh
# Run the live suite INSIDE a Linux Python container attached to the compose network.
# Useful where a driver cannot be installed on the host (cassandra-driver needs a
# libev/asyncio-capable build on Windows) and for CI parity.
#
#   scripts/it_docker_run.sh                       all reachable engines
#   scripts/it_docker_run.sh cassandra mongodb     only these engines
#   PYTHON_IMAGE=python:3.13-slim scripts/it_docker_run.sh postgres
#
# Services are addressed by compose service name and container port (no host ports).
set -eu
cd "$(dirname "$0")/.."
ENGINES="$(printf '%s,' "$@")"; ENGINES="${ENGINES%,}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-slim}"
DRIVERS="psycopg[binary] pymysql clickhouse-connect clickhouse-driver pymssql trino pymongo redis \
'elasticsearch>=8,<9' opensearch-py neo4j cassandra-driver duckdb asynch"
mkdir -p "${QB_IT_REPORT_DIR:-tests/integration/.reports}"
exec docker run --rm --network qb-integration_default \
  -v "$PWD:/src:ro" -v "$PWD/${QB_IT_REPORT_DIR:-tests/integration/.reports}:/reports" \
  -w /src -e PYTHONPATH=/src -e PYTHONDONTWRITEBYTECODE=1 \
  -e QB_IT_IN_DOCKER=1 -e QB_IT_REPORT=/reports/${QB_IT_REPORT_NAME:-linux}.json -e "QB_IT_ENGINES=$ENGINES" \
  -e QB_IT_POSTGRES_HOST=postgres -e QB_IT_POSTGRES_PORT=5432 \
  -e QB_IT_MYSQL_HOST=mysql -e QB_IT_MYSQL_PORT=3306 \
  -e QB_IT_MARIADB_HOST=mariadb -e QB_IT_MARIADB_PORT=3306 \
  -e QB_IT_CLICKHOUSE_HOST=clickhouse -e QB_IT_CLICKHOUSE_PORT=8123 \
  -e QB_IT_CLICKHOUSE_NATIVE_HOST=clickhouse -e QB_IT_CLICKHOUSE_NATIVE_PORT=9000 \
  -e QB_IT_CLICKHOUSE_NATIVE_HTTP_PORT=8123 \
  -e QB_IT_COCKROACH_HOST=cockroachdb -e QB_IT_COCKROACH_PORT=26257 \
  -e QB_IT_TIMESCALE_HOST=timescaledb -e QB_IT_TIMESCALE_PORT=5432 \
  -e QB_IT_MSSQL_HOST=mssql -e QB_IT_MSSQL_PORT=1433 \
  -e QB_IT_TRINO_HOST=trino -e QB_IT_TRINO_PORT=8080 \
  -e QB_IT_QUESTDB_HOST=questdb -e QB_IT_QUESTDB_PORT=8812 \
  -e QB_IT_MONGODB_HOST=mongodb -e QB_IT_MONGODB_PORT=27017 \
  -e QB_IT_REDIS_HOST=redis -e QB_IT_REDIS_PORT=6379 \
  -e QB_IT_ELASTICSEARCH_HOST=elasticsearch -e QB_IT_ELASTICSEARCH_PORT=9200 \
  -e QB_IT_OPENSEARCH_HOST=opensearch -e QB_IT_OPENSEARCH_PORT=9200 \
  -e QB_IT_NEO4J_HOST=neo4j -e QB_IT_NEO4J_PORT=7687 \
  -e QB_IT_CASSANDRA_HOST=cassandra -e QB_IT_CASSANDRA_PORT=9042 \
  "$PYTHON_IMAGE" sh -c "pip install -q -r requirements.txt pytest pytest-asyncio $DRIVERS ${QB_IT_EXTRA_PIP:-} \
    && python -m pytest tests/integration -m integration -o addopts= -q -p no:cacheprovider --tb=short -W ignore"
