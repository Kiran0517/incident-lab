"""Business impact tools: what actually happened to customers' orders."""
import psycopg

from ..config import DB_DSN

STATUS_MEANINGS = {
    "CONFIRMED": "Stock reserved and payment captured.",
    "REJECTED": "Inventory refused: insufficient stock or unknown product (business outcome, not a system fault).",
    "FAILED": "A dependency failed and the customer was NOT charged.",
    "PAYMENT_UNKNOWN": "Payment call timed out or was cut off; the customer MAY have been charged. Needs reconciliation.",
    "PENDING": "In progress. New orders are briefly PENDING while they are processed (one per active customer). "
               "Only PENDING orders older than 30 seconds are stuck: see stuck_pending_orders.",
}


def get_order_outcomes(minutes: int = 15) -> dict:
    """Order statuses per minute over the last N minutes, plus current stock levels."""
    with psycopg.connect(DB_DSN, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT date_trunc('minute', created_at) AS minute, status, count(*) FROM orders "
            "WHERE created_at > now() - %s * interval '1 minute' GROUP BY 1, 2 ORDER BY 1, 2",
            (int(minutes),),
        ).fetchall()
        stock = conn.execute("SELECT sku, stock FROM products ORDER BY sku").fetchall()
        stuck = conn.execute(
            "SELECT count(*) FROM orders WHERE status = 'PENDING' AND created_at < now() - interval '30 seconds'"
        ).fetchone()[0]
    per_minute = {}
    totals = {}
    for minute, status, count in rows:
        per_minute.setdefault(minute.isoformat(), {})[status] = count
        totals[status] = totals.get(status, 0) + count
    return {
        "window_minutes": minutes,
        "totals": totals,
        "per_minute": per_minute,
        "stuck_pending_orders": stuck,
        "stock_levels": {sku: level for sku, level in stock},
        "status_meanings": STATUS_MEANINGS,
    }
