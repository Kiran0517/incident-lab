CREATE TABLE IF NOT EXISTS products (
    sku   VARCHAR(32)  PRIMARY KEY,
    name  VARCHAR(255) NOT NULL,
    stock INT          NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS reservations (
    id         BIGSERIAL   PRIMARY KEY,
    order_ref  VARCHAR(64) NOT NULL,
    sku        VARCHAR(32) NOT NULL REFERENCES products (sku),
    qty        INT         NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dropped idx_reservations_order_ref: write-heavy table, index adds insert overhead.
DROP INDEX IF EXISTS idx_reservations_order_ref;

INSERT INTO products (sku, name, stock) VALUES
    ('SKU-1001', 'Mechanical Keyboard', 100000),
    ('SKU-1002', 'Wireless Mouse',      100000),
    ('SKU-1003', '27-inch Monitor',     100000)
ON CONFLICT (sku) DO NOTHING;
