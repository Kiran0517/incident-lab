# Incident Lab

An AI-assisted incident investigation platform, built on a small microservices system that I break on purpose.

When a production system goes down, most of the time spent fixing it goes into figuring out *why*: digging through logs, dashboards, request traces, and recent deploys. I wanted to see how far an LLM agent can get with that work if it has the same evidence an on-call engineer has. To make the test meaningful, the failures here are real. The services run under load, I inject faults (bad deploys, network latency, crashes), and the agent investigates live telemetry rather than canned logs with the answer already in them.

## Status

| Day | Work | Status | Write-up |
|---|---|---|---|
| 1 | Three Spring Boot services with tracing, metrics, and structured logs | Done | [Day 1](docs/day-1-services-and-observability.md) |
| 2 | Fault injection under load, investigation, fixes | Done | [Day 2](docs/day-2-incidents.md) |
| 3 | Read-only investigation tools for the agent | Done | [Day 3](docs/day-3-investigator-tools.md) |
| 4 | LLM agent investigating live incidents | Done | [Day 4](docs/day-4-ai-agent.md) |
| 5 | Dashboard with human approval for actions | Next | |
| 6 | Evaluation across incident types | Planned | |

Each write-up is meant to be readable without a deep backend background. I explain the idea first and then go into the technical detail.

## Architecture

```
client ──▶ order-service ──▶ inventory-service ──▶ PostgreSQL
           (8081)       └──▶ toxiproxy ──▶ payment-service ──▶ PostgreSQL
                             (fault injection)   (8083)

Traces    OpenTelemetry Java agent ──▶ Jaeger
Metrics   Prometheus scrapes each service (HTTP latency histograms, HikariCP pool)
Logs      Structured JSON, each line tagged with its trace ID
Deploys   Every deploy recorded with service, git SHA, and timestamp
Agent     Python tools over all of the above (read-only), driven by Gemini
```

## Stack

- **Services:** Java 21, Spring Boot 3.5, Spring JDBC, HikariCP, PostgreSQL 16
- **Observability:** OpenTelemetry, Jaeger, Prometheus, Grafana
- **Testing and faults:** k6 for load, Toxiproxy for network faults
- **Agent:** Python 3.12, Gemini API with function calling, Prometheus and Jaeger HTTP APIs, Docker SDK, psycopg
- **Infra:** Docker Compose

## Running it

```bash
docker compose up --build -d
./scripts/load-test.sh 20 30s                 # 20 virtual users for 30 seconds
./scripts/tool.sh list                        # investigation tools
./scripts/investigate.sh "Checkout is slow" 5 # agent run (needs GEMINI_API_KEY in .env)
```

Jaeger runs on :16686, Prometheus on :9090, and Grafana on :3000.

| Script | What it does |
|---|---|
| `scripts/load-test.sh [users] [duration]` | k6 load test |
| `scripts/generate-traffic.sh [count]` | A few orders, some deliberately rejected |
| `scripts/deploy.sh <service>` | Rebuilds and restarts a service and records the deploy |
| `scripts/reconcile.sh` | Settles orders whose payment outcome is unknown |
| `scripts/tool.sh` | Runs the agent's tools by hand |
| `scripts/investigate.sh "<problem>" [minutes]` | Runs the agent; reports are saved to `investigations/` |

## Results so far

- Baseline under load: about 1,200 orders/sec, p95 around 45 ms, no errors, with 3M+ rows in the reservations table.
- A deploy that dropped one index cut throughput from 1,197 to 29 orders/sec with zero errors. Health checks stayed green the whole time. Rolled back with `git revert`.
- The fault tests turned up four bugs I hadn't planted, including ephemeral port exhaustion (around 41,000 failed orders) and a case where 119 customers were charged while their orders stayed stuck in PENDING.
- Every payment that timed out turned out to have gone through. Timeouts are now recorded as `PAYMENT_UNKNOWN` and settled by a reconciliation job instead of being marked failed.
- The agent correctly called a healthy system healthy. On a live latency incident, its first answer blamed the wrong service. After I verified that, tightened its reasoning rules, and switched models, it found the actual cause on the second run. I haven't measured accuracy on incidents it wasn't tuned on yet; that's Day 6.
