package com.incidentlab.inventory;

import java.util.Map;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/inventory")
public class InventoryController {

    private final InventoryService service;

    public InventoryController(InventoryService service) {
        this.service = service;
    }

    @GetMapping("/{sku}")
    public Map<String, Object> get(@PathVariable String sku) {
        return service.getProduct(sku);
    }

    @PostMapping("/reserve")
    public ResponseEntity<Map<String, String>> reserve(@RequestBody ReserveRequest req) {
        if (req.sku() == null || req.qty() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "sku required and qty must be positive"));
        }
        boolean reserved = service.reserve(req.orderRef(), req.sku(), req.qty());
        return reserved
                ? ResponseEntity.ok(Map.of("status", "RESERVED"))
                : ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("status", "INSUFFICIENT_STOCK"));
    }

    @ExceptionHandler(EmptyResultDataAccessException.class)
    public ResponseEntity<Map<String, String>> notFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "product not found"));
    }

    public record ReserveRequest(String orderRef, String sku, int qty) {}
}
