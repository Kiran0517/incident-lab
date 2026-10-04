# Incident Lab: Engineering Notes

These notes explain what I built, why I built it this way, and what I learned along the way.
They are written so that anyone can follow them, with or without a technical background.
Each answer starts with a plain-English explanation and then gives the technical detail.

---

## What is this project?

When a website or app breaks, engineers have to figure out **what went wrong and why**, often
under pressure, at 2 a.m., while customers can't check out. They dig through thousands of
log messages, charts, and recent code changes to find the cause. This is called
**incident response**, and it is slow, stressful, and expensive.

**Incident Lab** is a platform where an AI assistant helps with that investigation. It looks
at the same evidence a human engineer would (logs, performance charts, request timelines,
and recent code changes), forms a hypothesis about the root cause, shows the evidence behind
it, and suggests a fix that a human must approve before anything happens.

To make this realistic, the AI investigates a **real, running system** that I break on
purpose in different ways, not fake pre-written data.

---

## The system I built (Day 1)

Think of it as a small online store split into three separate departments:

| Department | Real name | What it does |
|---|---|---|
| Order desk | `order-service` | Takes the customer's order and coordinates everything |
| Warehouse | `inventory-service` | Checks whether the item is in stock and sets it aside |
| Cashier | `payment-service` | Charges the customer |

All three keep their records in one shared filing cabinet: a **PostgreSQL database**.

**What happens when someone buys a keyboard:**

1. The order desk writes down the order as "pending."
2. It asks the warehouse: "Do you have one keyboard? Please set it aside."
3. If yes, it asks the cashier: "Please charge $49.99."
4. If that works, the order is marked "confirmed."
5. If the item doesn't exist or is out of stock, the order is marked "rejected."

### The "security cameras": observability

A system you can't see inside is impossible to debug. So I added three kinds of monitoring,
which together are called **observability**:

| Tool | Everyday analogy | What it tells us |
|---|---|---|
| **Jaeger** (traces) | A package-tracking timeline | The exact path one request took through every department, and how long each step took |
| **Prometheus** (metrics) | A car's dashboard gauges | Numbers over time: requests per second, error rates, how busy the database connections are |
| **Structured logs** | A detailed diary | Written notes of everything that happened, each stamped with the request it belongs to |
| **Grafana** | A control-room screen | Charts built from the metrics |

These are the same tools used by companies like Uber, Netflix, and most large tech teams.
The AI assistant (built in later stages) will use exactly these three sources of evidence.

### Glossary

- **Service / microservice:** a small, independent program that does one job. Large companies
  split their systems into many of these so teams can work and deploy independently.
- **Database:** where data is stored permanently (orders, stock levels, payments).
- **API / HTTP request:** how services talk to each other, like sending a structured message
  and waiting for a reply.
- **Docker / container:** a way to package each program with everything it needs, so the whole
  system starts with one command on any computer.
- **Latency:** how long something takes. Measured here in milliseconds (ms); 1,000 ms = 1 second.
- **Trace / span:** a trace is the full journey of one request; each step inside it is a span.

---

## Question 1: Why does the warehouse check and update stock in a single step?

### In plain English

Imagine there is **one keyboard left**, and two customers click "Buy" at the exact same moment.

If the warehouse did this in two separate steps:

1. Look at the shelf: "Yes, there's 1 left."
2. Take it off the shelf.

then both customers' requests could do step 1 at the same instant, both see "1 left," and
both get told "yes." The store has now sold **two keyboards it only had one of**. This is
called **overselling**, and it is a real, costly problem in e-commerce: angry customers,
cancelled orders, and refunds.

So instead, the warehouse does it as **one single, indivisible action**:
"Take one keyboard off the shelf, **but only if** there's at least one there."

It's like a ticket counter with one ticket left and a strict rule that only one person can
be served at a time. The second person has to wait, and when it's their turn, they're told
"sorry, sold out," instead of both being handed the same ticket.

### Technical detail

The code uses:

```sql
UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?
```

The check (`stock >= ?`) and the change (`stock - ?`) happen in **one atomic SQL statement**.
PostgreSQL takes a **row-level lock** on that product row during the update. If two requests
arrive at the same time, the second one waits for the first to finish, then re-evaluates the
condition against the **new** stock value. If no rows were updated, the code knows there
wasn't enough stock and rejects the order.

The unsafe alternative (read the value in Java, check it, then write it back) is a classic
**race condition** known as a "read-modify-write" bug.

### Why it matters

Correctness under concurrency is one of the most common things that goes wrong in real
production systems, and one of the most common topics in backend interviews.

---

## Question 2: Why do the services have time limits (timeouts) when calling each other?

### In plain English

Imagine you call a company and get put **on hold**. Most people hang up after a few minutes
and try something else. Now imagine a phone system that **never** hangs up and keeps waiting
forever.

That's what happens to a service without a timeout. If the warehouse becomes slow, the order
desk keeps waiting on every single call. Picture a restaurant with 200 waiters where each one
walks to the kitchen and waits for an order that never comes out. Soon **all 200 waiters are
standing in the kitchen**, and no one is left to greet new customers, even customers who only
wanted a glass of water that doesn't need the kitchen at all.

One slow part of the system has now taken down the whole thing. That chain reaction is called
a **cascading failure**, and it's one of the most common ways large systems go down.

With a timeout, the order desk says: "If the warehouse doesn't answer in 3 seconds, I'll stop
waiting, tell the customer something went wrong, and move on." The problem stays contained.

### Technical detail

In `ClientConfig.java`, the HTTP clients have a **2-second connect timeout** and a
**3-second read timeout**. The web server (Tomcat) handles requests with a limited thread
pool (200 threads by default). Without timeouts, each request blocked on a slow dependency
holds a thread indefinitely; once the pool is exhausted, the service becomes unresponsive.
Timeouts make the service **fail fast** and free the thread.

A natural next improvement is a **circuit breaker**: after repeated failures, the service
stops calling the broken dependency for a while instead of trying (and timing out) on every
request. Like a household fuse that trips to protect everything else.

### Why it matters

This exact failure (a slow dependency) is one of the scenarios the AI will investigate later.
Understanding how it spreads is key to diagnosing it.

---

## Question 3: What happens to reserved stock if the payment fails?

### In plain English

Suppose the warehouse sets a keyboard aside for a customer, but then the customer's **card is
declined**. In a well-run store, someone would put the keyboard **back on the shelf** so
another customer can buy it.

**Right now, my system doesn't do that.** The order is marked "failed," but the keyboard stays
set aside forever. Over time, the store's records would say there's less stock than there
really is, and it would turn away customers for items actually sitting on the shelf.

I left this gap in **on purpose** and documented it, because being honest about a system's
weaknesses (and knowing how to fix them) matters more than pretending a system is perfect.

### Technical detail

The order flow is: create order (PENDING) → reserve stock → capture payment → CONFIRMED.
If payment fails after the reservation succeeds, the order is set to FAILED, but there is no
**compensating action** to release the reservation, so inventory drifts from reality.

This is a well-known problem in distributed systems: you can't wrap calls to multiple
independent services in a single database transaction. The standard solution is the
**Saga pattern**: each step has a matching "undo" step (here: "release reservation"), which
runs automatically when a later step fails. A periodic **reconciliation job** that compares
reservations against confirmed orders is a common safety net.

### Why it matters

Keeping data consistent across multiple services is one of the hardest problems in modern
software. Recognizing the gap is the first step; the saga is a planned improvement.

---

## Question 4: How did the request timelines appear without writing any tracking code?

### In plain English

Imagine every package in a delivery company automatically gets a GPS tracker attached the
moment it enters the warehouse, without any employee doing anything extra. You can later see
exactly where each package went and how long it spent at each stop.

That's what happened here. I attached a small **monitoring add-on** to each service when it
starts up. It automatically records every incoming request, every call to another service,
and every database query, along with how long each took. I didn't have to change the
business code at all.

### Technical detail

Each service starts with the **OpenTelemetry Java agent**, configured in the `Dockerfile`:

```
java -javaagent:/otel/opentelemetry-javaagent.jar -jar app.jar
```

The `-javaagent` flag loads the agent before the application starts. It **modifies bytecode
as classes are loaded**, automatically wrapping Spring MVC controllers, HTTP clients, and
JDBC database calls so each becomes a **span**. Spans from different services are linked into
one **trace** by passing a trace ID in HTTP headers (the W3C `traceparent` standard), and
the agent also stamps that trace ID onto every log line. Traces are exported to Jaeger over
the **OTLP** protocol.

### Why it matters

Because every log line carries a `trace_id`, the AI assistant can jump from an error message
straight to the full timeline of the request that caused it. That connection is what makes
automated root-cause analysis possible.

---

## Question 5: Why did the traffic chart show activity even when nobody was using the store?

### In plain English

Imagine a manager who phones the store every 5 seconds to ask "How's business?" If you count
every phone call as a customer, it looks like the store has a steady trickle of customers all
day, even when it's completely empty.

That's what I saw. The monitoring tool (Prometheus) checks in on each service **every
5 seconds** to collect its numbers, and those check-ins were being counted as traffic.
One check every 5 seconds = **0.2 requests per second**, which is exactly the flat line I saw.

### Technical detail

Prometheus scrapes each service's `/actuator/prometheus` endpoint with a 5-second
`scrape_interval`, so 1 ÷ 5 = 0.2 req/s per service. These requests are recorded in
`http_server_requests_seconds_count` like any other request. To see only real traffic,
the query filters them out:

```
sum by (application, status) (rate(http_server_requests_seconds_count{uri!~"/actuator.*"}[1m]))
```

### Why it matters

Real monitoring data is full of noise like this. If the AI assistant counted monitoring
traffic as real users, it could draw wrong conclusions, so it must learn to filter it out.

---

## What I observed: anatomy of one order

Using Jaeger, I followed a single order through the system. The whole thing took
**about 12.5 milliseconds** (about 1/80th of a second).

| Step | Time |
|---|---|
| Write the order to the database | 0.38 ms |
| Order desk asks the warehouse (round trip) | 4.04 ms |
| ↳ Time the warehouse actually spent working | 2.63 ms |
| ↳ ↳ The warehouse's database work | about 0.4 ms |
| Order desk asks the cashier (round trip) | 4.69 ms |
| Mark the order as confirmed | 0.41 ms |

**What this tells me:**

1. **The database work is tiny; walking between departments is the main cost.** Each call
   between services adds about 1.4 ms of overhead just for sending and receiving the message.
   This is the hidden price of splitting a system into separate services.
2. **The warehouse and cashier are asked one after the other, on purpose.** You should never
   charge a customer before confirming the item is available.

This "healthy" picture is my baseline. When I break the system in the next stage, the same
view will show one step stretching from a few milliseconds to several seconds, and the AI
assistant's job will be to spot exactly which one and explain why.

---

## Next: Day 2

Introduce three real, repeatable failures and observe how each one appears in the evidence:

1. **Database connection pool exhaustion:** the warehouse runs out of "phone lines" to the
   filing cabinet under heavy load.
2. **A bad code release:** a change removes a database index, making lookups dramatically slower.
3. **Network slowdown:** artificial delay between the order desk and the cashier.
