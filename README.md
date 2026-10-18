# Incident Lab: AI-Assisted Incident Investigation

**In plain English:** when a website or app breaks, engineers have to figure out *why*, often in
the middle of the night while customers can't check out. They dig through logs, charts, request
timelines, and recent code changes, which can take hours. **Incident Lab** is a platform where an AI
assistant does that investigation: it gathers the same evidence a human would, identifies the
root cause, and shows its reasoning.

What makes it different from typical "AI + logs" demos: the failures are **real**. The system is a
running set of microservices that I break on purpose (bad deploys, network slowdowns, crashes),
and the AI investigates **live telemetry**, not pre-written fake logs with the answer planted inside.

## Project status

| Stage | What | Status | Report |
|---|---|---|---|
| Day 1 | Microservices + full observability (traces, metrics, logs) | ✅ Done | [Day 1 report](docs/day-1-services-and-observability.md) |
| Day 2 | Real failure injection, investigation, and fixes | ✅ Done | [Day 2 report](docs/day-2-incidents.md) |
| Day 3 | Read-only investigation tools for the AI agent | ✅ Done | [Day 3 report](docs/day-3-investigator-tools.md) |
| Day 4 | AI agent loop (LLM tool calling, root-cause report) | 🔜 Next | |
| Day 5 | Dashboard with human-approved actions | Planned | |
| Day 6 | Evaluation: measure how often the AI finds the right root cause | Planned | |

## Reports

Every day of work has its own report in [`docs/`](docs/), written so that **anyone can follow it**:
each section starts in plain English, then gives the technical detail. Read them in order:

1. **[Day 1: Building the system and its "security cameras"](docs/day-1-services-and-observability.md)**:
   a small online store split into three services, with monitoring that follows every request.
2. **[Day 2: Breaking things on purpose](docs/day-2-incidents.md)**:
   three planned failures, four unplanned ones, how each was investigated and fixed.
3. **[Day 3: The AI investigator's tools](docs/day-3-investigator-tools.md)**:
   the 8 tools that let an AI look at the system safely, and what testing them revealed.

## Architecture

```
                         ┌──────────────────────────────────────────────┐
client ──▶ order-service ─┼──▶ inventory-service ──▶ PostgreSQL          │
           (8081)         └──▶ toxiproxy ──▶ payment-service ──▶ PostgreSQL
                               (fault injection)   (8083)
                                    inventory: 8082

Observability:  OpenTelemetry agent ──▶ Jaeger (request traces)
                Prometheus ◀── scrapes each service (latency, errors, DB pool)
                Structured JSON logs, every line tagged with its trace ID
Change history: deployments table (service, git commit, time) for every deploy
Investigator:   Python tools that read all of the above (read-only) for the AI agent
```

## Tech stack

| Area | Technologies |
|---|---|
| Services | Java 21, Spring Boot 3.5, Spring JDBC, HikariCP |
| Data | PostgreSQL 16 |
| Observability | OpenTelemetry, Jaeger, Prometheus, Grafana, structured logging |
| Reliability testing | k6 (load), Toxiproxy (network faults) |
| Investigator | Python 3.12, Prometheus/Jaeger HTTP APIs, Docker SDK, psycopg |
| Infrastructure | Docker, Docker Compose |

## Quick start

```bash
docker compose up --build -d          # start everything (first build: ~5-10 min)
./scripts/load-test.sh 20 30s         # 20 virtual users ordering for 30 seconds
./scripts/tool.sh list                # list the investigation tools
./scripts/tool.sh call get_service_overview '{"minutes": 5}'
```

| UI | URL |
|---|---|
| Jaeger (request timelines) | http://localhost:16686 |
| Prometheus (metrics) | http://localhost:9090 |
| Grafana (dashboards) | http://localhost:3000 |

## Scripts

| Script | Purpose |
|---|---|
| `scripts/load-test.sh [users] [duration]` | k6 load test |
| `scripts/generate-traffic.sh [count]` | A few orders, including some deliberately rejected ones |
| `scripts/deploy.sh <service>` | Rebuild and restart a service, and record the deployment |
| `scripts/reconcile.sh` | Settle orders whose payment outcome is unknown |
| `scripts/tool.sh` | Run the AI investigator's tools by hand |

## Highlights so far (real measurements)

- **Healthy baseline:** ~1,200 orders/sec, p95 ~45 ms, 100% success (20 concurrent users, 3M+ records).
- **Bad deploy:** a dropped database index cut throughput **41x** (1,197 to 29 orders/sec) with
  **zero errors**; rolled back with `git revert` and fully recovered.
- **4 real bugs found that I didn't plant**, including ephemeral port exhaustion
  (~41,000 failed orders) and 119 customers charged while their orders stayed stuck.
- **Key lesson:** a timeout means "unknown," not "failed." Every timed-out payment checked had
  actually been charged; a reconciliation job now settles them against the payment records.
- **Investigator tools:** 32,055 log lines compressed into 3 meaningful groups; overview output
  33% smaller for the AI; malicious input (`8e9ac25; rm -rf /`) rejected by validation.

Full details: [Day 2 report](docs/day-2-incidents.md) and [Day 3 report](docs/day-3-investigator-tools.md).
