#!/usr/bin/env bash
# Runs the k6 load test inside Docker on the same network as the services.
# Usage: ./scripts/load-test.sh [virtual_users] [duration]
# Example: ./scripts/load-test.sh 20 60s
VUS=${1:-20}
DURATION=${2:-60s}
docker run --rm -i --network incident-lab_default \
  -e VUS="$VUS" -e DURATION="$DURATION" \
  grafana/k6 run - < "$(dirname "$0")/load-test.js"
