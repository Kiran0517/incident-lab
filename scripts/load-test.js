// Load test: many virtual users placing orders continuously.
// Usage: see scripts/load-test.sh
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  vus: __ENV.VUS ? parseInt(__ENV.VUS) : 20,
  duration: __ENV.DURATION || '60s',
};

const BASE_URL = __ENV.BASE_URL || 'http://order-service:8081';
const SKUS = ['SKU-1001', 'SKU-1002', 'SKU-1003'];

export default function () {
  const sku = SKUS[Math.floor(Math.random() * SKUS.length)];
  const res = http.post(
    `${BASE_URL}/orders`,
    JSON.stringify({ sku: sku, qty: 1, amount: 49.99 }),
    { headers: { 'Content-Type': 'application/json' }, timeout: '10s' }
  );
  check(res, { 'order confirmed (201)': (r) => r.status === 201 });
}
