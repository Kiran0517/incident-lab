#!/usr/bin/env bash
# Sends orders to order-service. SKU-9999 doesn't exist, so some orders are
# rejected (HTTP 409) on purpose -- realistic background noise for the AI later.
# Usage: ./scripts/generate-traffic.sh [count]
COUNT=${1:-50}
SKUS=(SKU-1001 SKU-1002 SKU-1003 SKU-9999)
for i in $(seq 1 "$COUNT"); do
  SKU=${SKUS[$((RANDOM % 4))]}
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8081/orders \
    -H "Content-Type: application/json" \
    -d "{\"sku\":\"$SKU\",\"qty\":1,\"amount\":49.99}")
  echo "order $i  sku=$SKU  -> HTTP $CODE"
done
