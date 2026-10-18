#!/usr/bin/env bash
# Asks the AI agent to investigate a problem using the read-only tools.
# Usage: ./scripts/investigate.sh "<what is wrong>" [minutes_to_look_back]
# Example: ./scripts/investigate.sh "Customers say checkout is slow" 15
cd "$(dirname "$0")/.."
mkdir -p investigations
docker compose run --rm -T investigator investigate "$1" "${2:-15}"
