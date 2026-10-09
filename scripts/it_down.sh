#!/usr/bin/env sh
# Stop and delete every qb-integration container, network and named volume.
set -eu
cd "$(dirname "$0")/.."
exec docker compose -p qb-integration -f docker/docker-compose.integration.yml --profile extended down -v --remove-orphans
