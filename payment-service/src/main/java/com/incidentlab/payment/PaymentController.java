package com.incidentlab.payment;

import java.math.BigDecimal;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/payments")
public class PaymentController {

    private final PaymentService service;

    public PaymentController(PaymentService service) {
        this.service = service;
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> capture(@RequestBody PaymentRequest req) {
        if (req.orderRef() == null || req.amount() == null || req.amount().signum() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "orderRef and positive amount required"));
        }
        long id = service.capture(req.orderRef(), req.amount());
        return ResponseEntity.status(HttpStatus.CREATED).body(Map.of("paymentId", id, "status", "CAPTURED"));
    }

    public record PaymentRequest(String orderRef, BigDecimal amount) {}
}
