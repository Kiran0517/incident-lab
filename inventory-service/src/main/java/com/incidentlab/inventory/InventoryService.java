package com.incidentlab.inventory;

import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class InventoryService {

    private static final Logger log = LoggerFactory.getLogger(InventoryService.class);
    private final JdbcTemplate jdbc;

    public InventoryService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Map<String, Object> getProduct(String sku) {
        return jdbc.queryForMap("SELECT sku, name, stock FROM products WHERE sku = ?", sku);
    }

    /**
     * Atomically decrements stock only if enough is available, then records the reservation.
     * The conditional UPDATE avoids a read-then-write race between concurrent orders.
     */
    @Transactional
    public boolean reserve(String orderRef, String sku, int qty) {
        int updated = jdbc.update(
                "UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?", qty, sku, qty);
        if (updated == 0) {
            log.warn("Reservation rejected (insufficient stock or unknown sku) orderRef={} sku={} qty={}",
                    orderRef, sku, qty);
            return false;
        }
        jdbc.update("INSERT INTO reservations (order_ref, sku, qty) VALUES (?, ?, ?)", orderRef, sku, qty);
        log.info("Stock reserved orderRef={} sku={} qty={}", orderRef, sku, qty);
        return true;
    }
}
