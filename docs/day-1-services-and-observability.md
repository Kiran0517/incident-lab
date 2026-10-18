# Day 1: Building the services and the observability stack

[Overview](../README.md) · [Day 1](day-1-services-and-observability.md) · [Day 2](day-2-incidents.md) · [Day 3](day-3-investigator-tools.md) · [Day 4](day-4-ai-agent.md)

## Summary

I built a small order system made of three Spring Boot services and set it up so every request can be followed end to end. A single order takes about 12.5 ms and touches all three services. That healthy baseline is what every later experiment gets compared against.

## Why this project

When something breaks in production, an engineer has to work out what went wrong and why, usually under time pressure. That means reading logs, looking at charts, tracing requests, and checking what was deployed recently. The end goal of Incident Lab is an AI agent that does that investigation and shows its evidence. Before any AI, though, I needed a realistic system to break and good telemetry to investigate it with. That's what Day 1 covers.

## The system

The easiest way to think about it is a small store with three departments:

| Service | Role |
|---|---|
| `order-service` | Takes the order and coordinates the other two |
| `inventory-service` | Checks stock and reserves it |
| `payment-service` | Charges the customer |

All three share one PostgreSQL database.

When someone orders a keyboard:

1. order-service saves the order as `PENDING`.
2. It asks inventory-service to reserve one keyboard.
3. If that works, it asks payment-service to charge $49.99.
4. If the charge goes through, the order becomes `CONFIRMED`. If the item doesn't exist or is out of stock, it becomes `REJECTED`.

## Observability

A system you can't see into is very hard to debug, so I set up three kinds of signals:

- **Traces (Jaeger):** the full path of a single request through every service, with timing for each step. It works like a package-tracking timeline.
- **Metrics (Prometheus, Grafana):** numbers over time, such as request rate, error rate, and how busy the database connection pool is.
- **Logs:** structured JSON, where every line carries the trace ID of the request that produced it.

That last part turns out to be important later. Because each log line carries a trace ID, you can jump from an error message straight to the full timeline of the request that caused it.

Everything runs in Docker, so the whole setup starts with one command.

## Design questions

These came up while building it. They're also the kind of questions that come up in backend interviews.

### 1. Why does inventory check and decrement stock in one statement?

Say there's one keyboard left and two people click Buy at the same moment. If inventory first reads the stock ("1 left") and then updates it, both requests can read "1 left" before either one writes, and the store sells two keyboards it doesn't have.

So the reservation is a single conditional update:

```sql
UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?
```

PostgreSQL takes a row-level lock for the update. The second request waits for the first, then re-checks `stock >= ?` against the new value. If no row was updated, there wasn't enough stock and the order is rejected. The alternative (read in Java, check, write back) is a classic read-modify-write race.

### 2. Why do the service-to-service calls have timeouts?

Without a timeout, if inventory gets slow, every order request waits on it indefinitely. Each waiting request holds a Tomcat thread (200 by default). Once they're all stuck, order-service stops responding completely, even for requests that don't touch inventory. One slow dependency ends up taking down its callers, which is a cascading failure.

The clients in `ClientConfig.java` use a 2-second connect timeout and a 3-second read timeout, so the caller fails fast and frees the thread. A circuit breaker would be the natural next step: after repeated failures, stop calling the dependency for a while instead of timing out on every request.

### 3. What happens to reserved stock if the payment fails?

At this point, nothing releases it. The order is marked `FAILED`, but the stock stays decremented, so inventory slowly drifts away from reality. I left this gap in on purpose and documented it.

The underlying problem is that you can't wrap calls to separate services in one database transaction. The usual answer is a saga, where each step has a compensating action (here, "release the reservation") that runs when a later step fails, plus a periodic reconciliation job as a safety net.

### 4. How did traces show up without any tracing code?

Each service starts with the OpenTelemetry Java agent:

```
java -javaagent:/otel/opentelemetry-javaagent.jar -jar app.jar
```

The agent rewrites bytecode as classes load and wraps Spring MVC handlers, HTTP clients, and JDBC calls so each one becomes a span. Spans from different services are tied into one trace through the W3C `traceparent` header, and the agent also adds the trace ID to log lines. Traces are exported to Jaeger over OTLP.

### 5. Why did the request-rate chart show traffic when nothing was running?

Prometheus scrapes each service's `/actuator/prometheus` endpoint every 5 seconds, and those scrapes count as HTTP requests too. One request every 5 seconds is exactly the 0.2 req/s I was seeing. Filtering with `uri!~"/actuator.*"` shows only real traffic. It's a small thing, but anything that analyzes these metrics automatically has to know about it.

## One order, step by step

Looking at a single order in Jaeger, the whole thing took about 12.5 ms:

| Step | Time |
|---|---|
| Insert the order | 0.38 ms |
| Call inventory (round trip) | 4.04 ms |
| Time spent inside inventory | 2.63 ms |
| Inventory's database work | ~0.4 ms |
| Call payment (round trip) | 4.69 ms |
| Mark the order confirmed | 0.41 ms |

Two things stood out. The database work is tiny; most of the time goes into the HTTP hops between services (about 1.4 ms of overhead on the inventory call alone). And inventory and payment are called one after the other, which is intentional, since you shouldn't charge someone before the item is reserved.

## Next

On Day 2 I broke this system in several ways while it was under load. Continue with [Day 2](day-2-incidents.md).
