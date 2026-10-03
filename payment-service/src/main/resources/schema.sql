CREATE TABLE IF NOT EXISTS payments (
    id         BIGSERIAL     PRIMARY KEY,
    order_ref  VARCHAR(64)   NOT NULL,
    amount     NUMERIC(12,2) NOT NULL,
    status     VARCHAR(16)   NOT NULL,
    created_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payments_order_ref ON payments (order_ref);
