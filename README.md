# Incident Lab: AI-Assisted Incident Investigation

Three Spring Boot microservices (order, inventory, payment) on PostgreSQL, fully
instrumented with OpenTelemetry, Prometheus, Jaeger, and Grafana. Later stages add
real fault injection and an AI agent that investigates failures from live telemetry.

## Architecture (Day 1)

    client -> order-service:8081 --> inventory-service:8082 --> PostgreSQL
                                 \-> payment-service:8083   --> PostgreSQL

    Traces:  OTel Java agent -> Jaeger (OTLP)
    Metrics: Prometheus scrapes /actuator/prometheus (HTTP latency histograms, HikariCP pool)
    Logs:    structured JSON (ECS) on stdout

## Run

    docker compose up --build -d
    ./scripts/generate-traffic.sh 50

| UI | URL |
|---|---|
| Jaeger (traces) | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

## Design notes

- Stock reservation uses a conditional `UPDATE ... WHERE stock >= ?` to avoid race conditions.
- Every downstream HTTP call has explicit connect/read timeouts.
- Known gap: a payment failure after stock reservation does not release the stock (saga planned).
