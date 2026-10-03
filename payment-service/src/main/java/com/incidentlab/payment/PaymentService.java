package com.incidentlab.payment;

import java.math.BigDecimal;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class PaymentService {

    private static final Logger log = LoggerFactory.getLogger(PaymentService.class);
    private final JdbcTemplate jdbc;

    public PaymentService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Simulated card capture: always succeeds and records the payment. */
    public long capture(String orderRef, BigDecimal amount) {
        Long id = jdbc.queryForObject(
                "INSERT INTO payments (order_ref, amount, status) VALUES (?, ?, 'CAPTURED') RETURNING id",
                Long.class, orderRef, amount);
        log.info("Payment captured paymentId={} orderRef={} amount={}", id, orderRef, amount);
        return id;
    }
}
