#!/usr/bin/env bash
# Reconciliation job: settles orders whose outcome is unknown (PENDING / PAYMENT_UNKNOWN)
# by checking the payments table, the source of truth for whether a customer was charged.
#   payment exists -> CONFIRMED (customer was charged)
#   no payment     -> FAILED    (customer was not charged)
# Only touches orders older than 1 minute, so in-flight orders are never affected.
# Usage: ./scripts/reconcile.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose exec -T postgres psql -U shop -d shop -v ON_ERROR_STOP=1 <<'SQL'
\echo 'Before reconciliation:'
SELECT status, count(*) FROM orders
WHERE status IN ('PENDING', 'PAYMENT_UNKNOWN') AND created_at < now() - interval '1 minute'
GROUP BY status;

BEGIN;

UPDATE orders o SET status = 'CONFIRMED'
WHERE o.status IN ('PENDING', 'PAYMENT_UNKNOWN')
  AND o.created_at < now() - interval '1 minute'
  AND EXISTS (SELECT 1 FROM payments p WHERE p.order_ref = o.order_ref);

UPDATE orders o SET status = 'FAILED'
WHERE o.status IN ('PENDING', 'PAYMENT_UNKNOWN')
  AND o.created_at < now() - interval '1 minute'
  AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.order_ref = o.order_ref);

COMMIT;

\echo 'Remaining unresolved after reconciliation (should be 0 rows):'
SELECT status, count(*) FROM orders
WHERE status IN ('PENDING', 'PAYMENT_UNKNOWN') AND created_at < now() - interval '1 minute'
GROUP BY status;
SQL
