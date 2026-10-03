CREATE TABLE IF NOT EXISTS orders (
    id         BIGSERIAL     PRIMARY KEY,
    order_ref  VARCHAR(64)   NOT NULL UNIQUE,
    sku        VARCHAR(32)   NOT NULL,
    qty        INT           NOT NULL,
    amount     NUMERIC(12,2) NOT NULL,
    status     VARCHAR(16)   NOT NULL,
    created_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);
