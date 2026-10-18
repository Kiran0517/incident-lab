# Day 3 Report: The AI Investigator's Tools

> **Incident Lab reports:** [Project overview](../README.md) · [Day 1: Services & monitoring](day-1-services-and-observability.md) · [Day 2: Breaking things on purpose](day-2-incidents.md) · [Day 3: The AI's investigation tools](day-3-investigator-tools.md) · [Day 4: The AI investigator goes live](day-4-ai-agent.md)
>
> **Who this is for:** anyone, technical or not. Each section starts with a plain-English explanation, then gives the technical detail for engineers.

## The short version

- An AI can't open a dashboard or scroll through logs by itself. It needs **tools**: small
  programs it can ask for specific evidence, like "show me the errors from the warehouse in the
  last 10 minutes."
- I built **8 tools** that give the AI the same views I used by hand on Day 2: performance charts,
  request timelines, logs, deployment history, code changes, and what happened to customers.
- Every tool is **read-only** (it can look, never change anything), **summarizes** huge amounts of
  data into something an AI can read (32,055 log lines became 3 groups), and **rejects dangerous
  input** (a hacking attempt hidden in a request was blocked).
- I tested every tool against the live system, and the numbers matched exactly
  (for example, 32,024 orders reported = 32,024 orders sent).
- Testing also exposed problems that would have **misled the AI**, such as monitoring traffic
  showing up as "customer requests." All were fixed before any AI was connected.


Before an AI can investigate an outage, it needs a way to **look at the system**. On Day 3, I built
8 tools that give it the same views I used by hand on Day 2: performance charts, request timelines,
logs, deployment history, code changes, and customer impact.

No AI runs yet. The goal of Day 3 was to make sure every tool returns **correct, compact, safe**
evidence, and to test each one by hand against the live system. On Day 4, the AI will call these
same tools on its own.

---

## In plain English: what is a "tool"?

Think of the AI as a detective who can't leave the office. It can't open Grafana or scroll through
logs itself, but it can **ask an assistant** to fetch specific evidence: "show me the error logs from
the warehouse for the last 10 minutes," or "what was deployed today?" Each tool is one kind of
question the assistant knows how to answer.

Modern AI models (Claude, GPT, Gemini) support this directly through **tool calling**: you describe
each tool (its name, what it does, and what inputs it takes), and the model decides which tool to
use next based on what it has learned so far.

---

## The 8 tools

| Tool | Question it answers | What I used manually on Day 2 |
|---|---|---|
| `get_service_overview` | Is each service up, busy, failing, slow? Is its database pool full? | Prometheus graphs |
| `query_metrics` | Any custom metric question | Typing PromQL queries |
| `find_traces` | Which recent requests were slowest or failed? | Jaeger search |
| `get_trace` | Step by step, where did one request spend its time? | Jaeger timeline view |
| `search_logs` | What errors or warnings happened, and how many of each? | `docker compose logs \| grep` |
| `get_recent_deployments` | What changed recently, and exactly when? | The deployments table |
| `get_commit_diff` | What did a specific code change actually change? | `git show` |
| `get_order_outcomes` | What happened to customers' orders? | SQL status queries |

---

## Design decisions (and why)

### 1. Read-only

The tools can **look but never change anything**. An AI that investigates should not be able to
restart services or edit data on its own. Any action (like a rollback) will require human approval
in a later stage.

### 2. Compressed output

AI models have a limited "working memory" (the **context window**), and every word they read costs
money and time (measured in **tokens**). Raw evidence is huge, so each tool summarizes it:

- **Logs are grouped.** 32,055 log lines like `Stock reserved orderRef=8f3a... sku=SKU-1001` become
  **one group** with a count, by replacing IDs and numbers with placeholders
  (`orderRef=<uuid> sku=SKU-<n>`). Result: 32,055 lines → **3 groups**.
- **Metrics are summarized** as min / max / average / last / peak time, plus a few samples.
  A flat line (like "database pool size: always 10") shows no samples at all.
- **Compact samples:** `"18:28:48 411.67"` instead of a 4-line JSON array.
  Measured result: the overview went from **9,878 to 6,640 characters (33% smaller)**
  with the same information.

### 3. Errors returned as data

If a tool fails (a timeout, bad input), it returns a readable message like
`{"error": "ReadTimeout: ..."}` instead of crashing. The AI can read it and try something else,
just as a human would after a failed query.

### 4. Input validation (security)

An AI agent with tools is a **security surface**. Text inside a log line could try to trick the
AI into doing something harmful (this is called **prompt injection**). So safety is enforced in
the tools themselves, not by trusting the AI:

```
get_commit_diff("8e9ac25; rm -rf /")
→ {"error": "ValueError: sha must be 7-40 hex characters"}   (nothing executed)
```

Commands are run with argument lists (never through a shell), and every ID is checked against a
strict pattern.

### 5. Built for the AI's context

Tool results include short **notes** that explain how to read them, for example:
"`toxiproxy` is the network proxy in front of payment-service" and
"HTTP 409 on POST /orders is a rejected order (a business outcome), not a system failure."
The tool definitions use **JSON Schema**, the exact format AI tool-calling APIs expect.

---

## Problems found while testing (and fixed)

Testing each tool by hand against the real system exposed problems that would have misled the AI:

| Problem | What would have gone wrong | Fix |
|---|---|---|
| Trace search returned Prometheus's own scrapes (`GET /actuator/prometheus`) | The AI would investigate monitoring noise instead of customer orders | Filter traces by business endpoint |
| Fetching more traces to filter them caused a 15-second timeout in Jaeger | The tool would fail during the incidents it's meant for | Ask Jaeger for the right endpoint directly (server-side filtering): ~1 second |
| Background database spans (`order-service shop`) appeared as "requests" | More noise in the slowest-request list | Same server-side filter |
| Repeated identical samples in flat metrics | Wasted tokens | Skip samples for flat lines |

### Traps the AI will need to handle

These are real signals in the data that a careless investigator would misread:

- **Request rate looked like 570/sec when the real rate was 1,067/sec.** The metric averages over
  1 minute, and the traffic lasted only 30 seconds. Short bursts look smaller than they are.
- **`Thread starvation or clock leap detected (delta=1d23h40m...)`** is a warning caused by my laptop
  going to sleep. It's harmless, and the AI must not blame it.
- **`has_error: true` on a rejected order (HTTP 409)** is technically an error status, but it is
  normal business behavior, not a system fault.

---

## Verified against the live system

| Tool | Check | Result |
|---|---|---|
| `get_service_overview` | p95 vs. k6 load test | 45–67 ms vs. 46.9 ms ✓ |
| `get_order_outcomes` | Confirmed orders vs. k6 | 32,024 = 32,024 ✓ exact |
| `search_logs` | Rejection warnings vs. rejected orders sent | 10 = 10 ✓ |
| `find_traces` | Only real customer orders, with HTTP status | ✓ |
| `get_trace` | Full request path including SQL statements | ✓ |
| `get_recent_deployments` | All 7 Day 2 deploys with exact times | ✓ |
| `get_commit_diff` | Shows the dropped index from Incident #1 | ✓ |
| `get_commit_diff` | Malicious input rejected | ✓ |

---

## Known limitations

- **Trace search** looks at the 50 most recent matching requests. To find slow requests during an
  incident, the AI should pass `min_duration_ms` so Jaeger returns only slow ones.
- **Logs are read through the Docker API**, which is fine for a local lab. In production you'd use a
  log platform such as Loki or Elasticsearch instead of access to the Docker socket.
- **Metrics use 1-minute windows**, so very short spikes are smoothed out.

---

## Glossary (plain English)

| Term | Meaning |
|---|---|
| **Tool calling** | A feature of modern AI models: you describe tools, and the AI decides which one to use and with what inputs. |
| **Token** | The unit AI models read and are billed by; roughly 4 characters of text. Fewer tokens = cheaper and faster. |
| **Context window** | How much text an AI can "keep in mind" at once. Raw logs would overflow it, so the tools summarize. |
| **Trace / span** | A trace is the full journey of one request through the system; each step in it is a span. |
| **PromQL** | The query language for Prometheus, the tool that stores performance numbers over time. |
| **p95** | 95% of requests were at least this fast. Engineers use it because averages hide slow experiences. |
| **JSON** | A simple, structured text format that both programs and AI models read easily. |
| **JSON Schema** | A standard way to describe what inputs a tool accepts; AI tool-calling APIs use it. |
| **Prompt injection** | Hidden instructions in text (like a log line) that try to trick an AI into doing something harmful. |
| **Read-only** | Can look at data but never change it. |
| **Docker socket** | The control channel for Docker; the log tool uses it to read container logs. |

---

## How to use the tools

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

Code: [`investigator/`](../investigator/) (Python 3.12, runs in Docker with read-only access to the repo).

## What happened next

On Day 4, I connected an AI model to these tools. It investigated a healthy system correctly,
got a live incident partly wrong on the first try, and found the correct root cause after
improvements.

**Continue reading:** [Day 4 Report: The AI investigator goes live](day-4-ai-agent.md)
