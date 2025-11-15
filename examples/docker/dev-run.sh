#!/bin/sh
# Simple helper script to build & run the dev image using docker compose
# Run from repository root: ./examples/docker/dev-run.sh
set -e

docker compose -f docker-compose.yml up --build -d

echo "Container started. To follow logs: docker compose logs -f"
echo "To stop: docker compose down"
