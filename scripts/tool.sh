#!/usr/bin/env bash
# Runs the investigator's tools against the live system (inside Docker).
# Usage: ./scripts/tool.sh list
#        ./scripts/tool.sh call <tool_name> '<json args>'
# Example: ./scripts/tool.sh call get_service_overview '{"minutes": 10}'
cd "$(dirname "$0")/.."
docker compose run --rm -T investigator "$@"
