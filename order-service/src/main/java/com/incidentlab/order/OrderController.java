package com.incidentlab.order;

import java.util.Map;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
public class OrderController {

    private final OrderService service;

    public OrderController(OrderService service) {
        this.service = service;
    }

    @PostMapping
    public ResponseEntity<?> create(@RequestBody OrderService.CreateOrderRequest req) {
        if (req.sku() == null || req.qty() <= 0 || req.amount() == null || req.amount().signum() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "sku, positive qty and positive amount required"));
        }
        OrderService.OrderResult result = service.placeOrder(req);
        HttpStatus status = "CONFIRMED".equals(result.status()) ? HttpStatus.CREATED : HttpStatus.CONFLICT;
        return ResponseEntity.status(status).body(result);
    }

    @GetMapping("/{orderRef}")
    public Map<String, Object> get(@PathVariable String orderRef) {
        return service.getOrder(orderRef);
    }

    @ExceptionHandler(DownstreamException.class)
    public ResponseEntity<Map<String, String>> downstream(DownstreamException e) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(Map.of("error", "dependency unavailable", "dependency", e.getDependency()));
    }

    @ExceptionHandler(EmptyResultDataAccessException.class)
    public ResponseEntity<Map<String, String>> notFound() {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "order not found"));
    }
}
