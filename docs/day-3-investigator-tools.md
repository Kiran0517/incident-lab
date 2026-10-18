# Day 3: Investigation tools for the agent

[Overview](../README.md) · [Day 1](day-1-services-and-observability.md) · [Day 2](day-2-incidents.md) · [Day 3](day-3-investigator-tools.md) · [Day 4](day-4-ai-agent.md)

## Summary

An LLM can't open Grafana or scroll through logs. It needs tools: small functions it can call to fetch specific evidence, like "error logs from inventory in the last 10 minutes" or "what was deployed today." I built eight of them in Python, covering the same views I used by hand on Day 2. They're read-only, they summarize large amounts of data into something a model can actually read, and they validate their inputs.

There's no AI in this step. The point was to make sure each tool returns correct, compact evidence before anything depends on it. I tested every one against the live system, and the numbers matched exactly. Testing also caught a few problems that would have sent the agent in the wrong direction.

## What a tool is

Modern LLMs support *function calling*. You describe each tool (its name, what it does, and its inputs), and the model decides which one to call next based on what it has learned so far. The program runs the tool and hands the result back. A rough analogy is a detective who can't leave the office but can send an assistant to collect specific evidence.

## The tools

| Tool | Question it answers | What I used manually on Day 2 |
|---|---|---|
| `get_service_overview` | Is each service up, busy, failing, slow? Is the DB pool saturated? | Prometheus graphs |
| `query_metrics` | Any other metric question (PromQL) | Prometheus |
| `find_traces` | Which recent requests were slowest or failed? | Jaeger search |
| `get_trace` | Where did one request spend its time? | Jaeger trace view |
| `search_logs` | Which errors happened, and how often? | `docker compose logs \| grep` |
| `get_recent_deployments` | What changed, and exactly when? | Deployments table |
| `get_commit_diff` | What did a given commit change? | `git show` |
| `get_order_outcomes` | What happened to customers' orders? | SQL queries |

The code is in [`investigator/`](../investigator/). It runs in its own container with read-only access to the repo.

## Design decisions

**Read-only.** The tools can look but can't change anything. An agent that investigates shouldn't be able to restart services or touch data on its own. Any action, like a rollback, will need human approval.

**Compact output.** Models have a limited context window, and every token costs time and money. Raw evidence is far too big, so each tool summarizes:

- Logs are grouped. IDs and numbers are replaced with placeholders (`orderRef=<uuid> sku=SKU-<n>`), so lines that differ only in their values collapse into one group with a count. In one test, 32,055 log lines became 3 groups.
- Metrics are reduced to min, max, average, last value, and peak time, plus a few samples. A flat series (like a pool size that's always 10) gets no samples at all.
- Samples are written as compact strings like `"18:28:48 411.67"`. Together with the flat-series change, this took the overview from 9,878 to 6,640 characters, about 33% smaller, with the same information.

**Errors come back as data.** If a tool fails (a timeout, bad input), it returns something like `{"error": "ReadTimeout: ..."}` instead of crashing, so the agent can read it and try something else.

**Input validation.** An agent with tools is a security surface. Text inside a log line could try to steer the model into doing something harmful (prompt injection), so the tools don't trust their inputs:

```
get_commit_diff("8e9ac25; rm -rf /")
→ {"error": "ValueError: sha must be 7-40 hex characters"}
```

Commands run with argument lists rather than through a shell, and IDs are checked against strict patterns.

**Context for the model.** Results include short notes on how to read them, for example that `toxiproxy` is the proxy in front of payment-service, or that an HTTP 409 on `POST /orders` is a rejected order rather than a system fault. Tool definitions use JSON Schema, which is the format function-calling APIs expect.

## Problems found while testing

| Problem | Effect on the agent | Fix |
|---|---|---|
| Trace search returned Prometheus's own scrapes (`GET /actuator/prometheus`) | It would investigate monitoring noise instead of orders | Search by business endpoint |
| Fetching more traces and filtering them in Python made Jaeger time out after 15 s | The tool would fail during the incidents it exists for | Let Jaeger filter by operation server-side (~1 s) |
| Background DB spans (`order-service shop`) showed up as requests | More noise in the slowest-request list | Same server-side filter |
| Flat metrics repeated identical samples | Wasted tokens | Skip samples for flat series |

There are also a few things in the data the agent will have to handle correctly:

- The request rate looked like 570/s when the real rate was 1,067/s. Rates are computed over one-minute windows, and that burst lasted only 30 seconds.
- A `Thread starvation or clock leap detected (delta=1d23h40m...)` warning came from my laptop going to sleep. It's harmless.
- Rejected orders (HTTP 409) show `has_error: true` at the HTTP level, but they're normal business behavior.

## Verification

| Tool | Check | Result |
|---|---|---|
| `get_service_overview` | p95 vs. the k6 run | 45–67 ms vs. 46.9 ms |
| `get_order_outcomes` | Confirmed orders vs. k6 | 32,024 and 32,024 |
| `search_logs` | Rejection warnings vs. rejected orders sent | 10 and 10 |
| `find_traces` | Only real orders, with HTTP status | Yes |
| `get_trace` | Full request path including SQL | Yes |
| `get_recent_deployments` | All 7 Day 2 deploys with exact times | Yes |
| `get_commit_diff` | Shows the dropped index from Incident 1 | Yes |
| `get_commit_diff` | Rejects malicious input | Yes |

## Known limitations

- Trace search looks at the 50 most recent matching requests. During an incident, the agent should pass `min_duration_ms` so Jaeger returns only slow requests.
- Logs are read through the Docker API. That's fine locally, but in production I'd use a log store like Loki or Elasticsearch rather than giving anything access to the Docker socket.
- One-minute rate windows smooth out very short spikes.

## Usage

```bash
./scripts/tool.sh list
./scripts/tool.sh call get_service_overview '{"minutes": 10}'
./scripts/tool.sh call search_logs '{"service": "order-service", "minutes": 10, "level": "ERROR"}'
./scripts/tool.sh call find_traces '{"service": "order-service", "minutes": 10, "min_duration_ms": 1000}'
./scripts/tool.sh call get_trace '{"trace_id": "<trace id>"}'
./scripts/tool.sh call get_recent_deployments '{"minutes": 120}'
./scripts/tool.sh call get_commit_diff '{"sha": "<commit>"}'
./scripts/tool.sh call get_order_outcomes '{"minutes": 15}'
```

## Terms

- **Function calling:** the model asks the program to run a named tool with specific inputs, then reads the result.
- **Token:** the unit models read and are billed by, roughly four characters of text.
- **Context window:** how much text a model can take into account at once.
- **Trace / span:** a trace is one request's full journey; each step in it is a span.
- **PromQL:** Prometheus's query language.
- **Prompt injection:** instructions hidden in data (a log line, for example) that try to manipulate a model.

## Next

On Day 4 I connected an LLM to these tools and let it investigate a live incident. Continue with [Day 4](day-4-ai-agent.md).
