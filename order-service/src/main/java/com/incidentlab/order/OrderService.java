package com.incidentlab.order;

import java.math.BigDecimal;
import java.net.ConnectException;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

@Service
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final JdbcTemplate jdbc;
    private final RestClient inventoryClient;
    private final RestClient paymentClient;

    public OrderService(JdbcTemplate jdbc,
                        @Qualifier("inventoryClient") RestClient inventoryClient,
                        @Qualifier("paymentClient") RestClient paymentClient) {
        this.jdbc = jdbc;
        this.inventoryClient = inventoryClient;
        this.paymentClient = paymentClient;
    }

    /**
     * Flow: create PENDING order -> reserve stock -> capture payment -> CONFIRMED.
     *
     * Every exit path sets a final status, so no order is left PENDING.
     * Incident (Day 2): a read timeout surfaced as CancellationException, which the old
     * catch (RestClientException) missed, leaving 119 orders PENDING after they were charged.
     *
     * Known gap: if payment fails after stock is reserved, the reservation is not released
     * (saga/compensation planned).
     */
    public OrderResult placeOrder(CreateOrderRequest req) {
        String orderRef = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO orders (order_ref, sku, qty, amount, status) VALUES (?, ?, ?, ?, 'PENDING')",
                orderRef, req.sku(), req.qty(), req.amount());

        try {
            inventoryClient.post()
                    .uri("/inventory/reserve")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("orderRef", orderRef, "sku", req.sku(), "qty", req.qty()))
                    .retrieve()
                    .toBodilessEntity();
        } catch (HttpClientErrorException.Conflict e) {
            updateStatus(orderRef, "REJECTED");
            log.warn("Order rejected: insufficient stock orderRef={} sku={}", orderRef, req.sku());
            return new OrderResult(orderRef, "REJECTED");
        } catch (RuntimeException e) {
            updateStatus(orderRef, "FAILED");
            log.error("Inventory call failed orderRef={}", orderRef, e);
            throw new DownstreamException("inventory-service", e);
        }

        try {
            paymentClient.post()
                    .uri("/payments")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("orderRef", orderRef, "amount", req.amount()))
                    .retrieve()
                    .toBodilessEntity();
        } catch (HttpClientErrorException e) {
            // Payment explicitly rejected the request (4xx): the card was not charged.
            updateStatus(orderRef, "FAILED");
            log.error("Payment rejected orderRef={} status={}", orderRef, e.getStatusCode(), e);
            throw new DownstreamException("payment-service", e);
        } catch (RuntimeException e) {
            if (isConnectFailure(e)) {
                // Could not even connect: payment never received the request, so no charge happened.
                updateStatus(orderRef, "FAILED");
                log.error("Payment call failed (could not connect) orderRef={}", orderRef, e);
            } else {
                // Request was sent but no answer arrived in time: the charge may have happened.
                // A timeout is not a failure; the outcome is unknown and must be reconciled.
                updateStatus(orderRef, "PAYMENT_UNKNOWN");
                log.error("Payment outcome unknown, needs reconciliation orderRef={}", orderRef, e);
            }
            throw new DownstreamException("payment-service", e);
        }

        updateStatus(orderRef, "CONFIRMED");
        log.info("Order confirmed orderRef={} sku={} qty={}", orderRef, req.sku(), req.qty());
        return new OrderResult(orderRef, "CONFIRMED");
    }

    public Map<String, Object> getOrder(String orderRef) {
        return jdbc.queryForMap(
                "SELECT order_ref, sku, qty, amount, status, created_at FROM orders WHERE order_ref = ?", orderRef);
    }

    private void updateStatus(String orderRef, String status) {
        jdbc.update("UPDATE orders SET status = ? WHERE order_ref = ?", status, orderRef);
    }

    /** True if the root cause was a refused/failed TCP connection (request never sent). */
    private static boolean isConnectFailure(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof ConnectException) {
                return true;
            }
        }
        return false;
    }

    public record CreateOrderRequest(String sku, int qty, BigDecimal amount) {}

    public record OrderResult(String orderRef, String status) {}
}
