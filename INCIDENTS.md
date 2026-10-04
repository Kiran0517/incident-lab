# Incident Reports (Day 2)

On Day 2, I deliberately broke my system in three different ways while it was handling heavy
traffic, then investigated each failure the way an on-call engineer would. Along the way, the
system also failed in **four ways I did not plan**, and those turned out to be the most
valuable findings.

Each report below follows the format real tech companies use after an outage, called a
**postmortem**: what happened, who was affected, why it happened, how it was fixed, and what
was learned. Every number here comes from real measurements, not estimates.

> **Quick refresher:** the system is a small online store with three services: an **order desk**
> (`order-service`), a **warehouse** (`inventory-service`), and a **cashier** (`payment-service`).
> See [NOTES.md](NOTES.md) for the full Day 1 explanation.

---

## Summary

| # | Incident | Planned? | Customer impact | Root cause | Fixed? |
|---|---|---|---|---|---|
| A1 | Store sold out | No | Orders rejected | Test data ran out | Yes (restocked) |
| A2 | Monitoring crashed | No | Lost visibility | Unlimited trace storage | Yes |
| A3 | Order desk couldn't open connections | No | ~41,000 failed orders | Port exhaustion | Yes |
| 1 | Bad code release | Yes | Store 41× slower | Missing database index | Yes (rolled back) |
| 2 | Slow network to payment | Yes | 119 customers charged, orders stuck | Unhandled error type | Yes |
| 3 | Payment service crash | Yes | 319 orders in unknown state | Crash hidden by proxy | Handled by reconciliation |

---

## How I measured "healthy" first

You can't recognize "broken" without knowing what "normal" looks like. I used **k6**, a
professional load-testing tool, to simulate 20 customers ordering non-stop.

| Measurement | Healthy value |
|---|---|
| Orders processed per second | ~1,200 |
| 95% of orders finished within | ~45 ms (0.045 seconds) |
| Success rate | 100% |

**"p95"** means 95% of requests were at least this fast. Engineers use it instead of averages
because averages hide the slow experiences that frustrate real customers.

---

## Incident A: The test that went wrong in three unexpected ways

### In plain English

I planned to ship a bad code change while traffic was flowing and watch it slow the system
down. Instead, 67% of orders failed, but they failed **instantly**, which didn't match what a
slow system looks like. When something doesn't fit your theory, the theory is wrong.
So I investigated, the way a detective rebuilds a timeline from evidence.

### The real timeline (all times UTC)

| Time | What happened | How I know |
|---|---|---|
| 22:03 | Load test starts, orders succeed | 119,407 confirmed orders that minute |
| 22:04 | **The store sold out** | Stock = 0 for all products; 82,183 rejections |
| ~22:04 | **The monitoring tool (Jaeger) crashed** | Container exit code 137 (killed for using too much memory) |
| 22:05–22:06 | **Order desk couldn't open connections** | ~41,000 failed orders: "Cannot assign requested address" |
| ~22:07 | Load test ends | |
| 22:07:56 | The bad code change is deployed | Deployment log |

**The key insight:** the bad deploy happened **after** the traffic stopped. It caused none of
these failures, even though it was the most obvious suspect. A careless investigation
(human or AI) would have blamed it. **Checking exact timestamps proved it innocent.**

### A1: The store sold out

Each product started with 100,000 units. Earlier tests had sold about 94,000; this test sold
the remaining 206,011. Total: ~300,000, exactly the starting stock. Rejections are fast
("sorry, sold out"), which explained the instant failures.

**Fix:** restocked to 10 million units per product.

### A2: The monitoring tool ran out of memory

Jaeger (the request-timeline tool) stores every timeline in memory with no limit by default.
About 600,000 orders × 10 steps each was too much, and the operating system killed it.

**Why it matters:** during a real outage, this is exactly when you need monitoring most,
and it's exactly when heavy traffic is most likely to knock it over.

**Fix:** limited Jaeger to the newest 50,000 timelines (commit `f5f0508`).

### A3: The order desk ran out of "phone lines" (port exhaustion)

**In plain English:** every time one service calls another, it needs a temporary "return
address" called a **port**. A computer has only about 28,000 of them. After a connection
closes, its port stays reserved for about 60 seconds before it can be reused.

The HTTP client I originally used kept only a handful of connections open for reuse. At about
2,600 requests per second, it kept opening new connections and burning through ports faster
than they were freed. Eventually there were none left, and every new call failed with
`Cannot assign requested address`.

It's like a call center that hangs up after every sentence and redials, and each phone line
must rest for a minute before reuse. Eventually every line is resting.

**This is a classic production incident** that real companies hit when traffic grows.

**Fix:** switched to a client with a proper **connection pool**, which keeps a few connections
open and reuses them thousands of times (commit `09ccca9`, deployment #4).

---

## Incident 1: The "harmless" cleanup that made the store 41× slower

### In plain English

The day before, I added a safety feature: before reserving stock, the warehouse checks
"have I already reserved stock for this order?" so a retried request can't reserve twice.
That check is fast because of a database **index**, which works like the index at the back
of a book: it lets the database jump straight to the right page instead of reading every page.

Then a change was shipped with the message *"drop unused index to reduce write overhead."*
It sounds reasonable, and teams make this exact change in real life. But the index wasn't
unused. Without it, every single order forced the database to read **all 3 million past
reservations** to answer one question.

### Impact

| Measurement | Before | After the bad change | Change |
|---|---|---|---|
| One order (no other traffic) | 0.012 s | 0.550 s | ~45× slower |
| Orders per second (under load) | 1,197 | **29** | **41× fewer** |
| p95 response time | 45 ms | **1,040 ms** | **23× slower** |
| Errors | 0% | **0%** | No change! |

### Why "no errors" is the scariest part

The system never "broke": every order eventually succeeded, and health checks said "UP."
Engineers call this a **brownout**. In real life, customers abandon carts long before a
page takes over a second, but no error alarm would ever fire. **Only speed and throughput
measurements revealed it.**

### How the evidence pointed to the cause

1. **Database query plan:** PostgreSQL's own explanation showed a **"Parallel Seq Scan"**
   (reading every row) taking **1,232 ms**, instead of an instant index lookup.
2. **Connection pool:** the warehouse has 10 database connections. They were pinned at
   10/10 with a queue of requests waiting. Each slow query held a connection for ~0.5 s, so
   everything else waited in line.
3. **Deployment log:** the slowdown started right after deployment #3, commit `8e9ac25`.

### Fix: rollback

In a real incident, the first priority is to **stop the bleeding**: undo the change, then
investigate calmly. I used `git revert`, which creates a new commit that undoes the bad one,
so history shows both the mistake and the fix (commit `c0e5958`, deployment #5).

| After rollback | Value |
|---|---|
| Orders per second | **1,227** (fully recovered) |
| p95 | **36.8 ms** |

### Technical detail

- Query: `SELECT COUNT(*) FROM reservations WHERE order_ref = ?` inside a `@Transactional` method,
  so the connection is held for the entire slow scan.
- The failure chain is common: **missing index → slow query → connections held longer →
  pool exhaustion → request queuing → latency explosion.**
- Prevention ideas: query-plan checks in CI, alerting on p95 latency (not just errors), and
  checking index usage stats (`pg_stat_user_indexes`) before dropping any index.

---

## Incident 2: Slow network, and customers charged for "failed" orders

### In plain English

This time I changed **no code at all**. I used a tool called **Toxiproxy** (made by Shopify)
to add 2.5 seconds (± 1 second) of delay to the cashier's replies, simulating a slow network.
The order desk gives up after waiting 3 seconds.

I expected the slow orders to be marked "failed." Instead, **119 orders were stuck as
"pending" forever**, with no error message logged anywhere. When I checked further:

> **All 119 customers had been charged.** Their stock was reserved, their payment was taken,
> they saw an error page, and their order would never complete.

### Why it happened

When the 3-second timer ran out, the newer HTTP client (from the A3 fix) reported the problem
as a **`CancellationException`**, a type of error my code wasn't expecting. My error handling
only caught one specific family of errors (`RestClientException`), so this one slipped
straight past it: no status update, no log line.

**A fix for one bug had quietly created another.** That happens constantly in real software,
which is why testing under realistic failure conditions matters.

### The deeper lesson: a timeout is not a failure

Even if the error had been caught, marking those orders "failed" would have been **wrong**.
The cashier *did* charge the card; only the reply was slow. When you time out, you don't know
what happened. **The honest answer is "unknown."** Payment companies like Stripe design their
whole APIs around this problem.

### Fix (commit `5d31f5e`, deployment #7)

1. **Catch every error**, so no order is ever left silently stuck.
2. **Separate "definitely failed" from "unknown":**
   - Couldn't even connect → the cashier never got the request → **FAILED** (safe: no charge).
   - Connected, sent the request, then no reply → **PAYMENT_UNKNOWN** (the charge may have happened).
3. **A reconciliation job** (`scripts/reconcile.sh`, commit `f2a4502`) settles unknown orders
   by checking the payments table, the source of truth:
   - payment exists → **CONFIRMED**
   - no payment → **FAILED**

### Proof the fix works (same incident, re-run)

| Check | Before fix | After fix |
|---|---|---|
| Orders stuck forever | **119** | **0** |
| Orders honestly marked unknown | 0 | **45** |
| Unknown orders with a log line | 0 | **45** |

Then reconciliation resolved all 164 unknown orders (119 old + 45 new): **all 164 had been
charged** and became CONFIRMED. If they had been marked "failed," 164 paying customers would
have been told their order failed, and many would have ordered again and been charged twice.

### Ruling out the deploy

The last deployment (#6) was at 22:43:29. Traffic ran healthy from ~22:46:40 until the delay
was injected at 22:47:39. More than 4 minutes passed with healthy traffic in between, so
the deploy was not the cause.

---

## Incident 3: The cashier crashed

### In plain English

I stopped the payment service completely for about 30 seconds while orders were flowing.

**Prediction (made before running it):** these orders would *not* be marked "failed," because
the order desk doesn't talk to the cashier directly. It talks to Toxiproxy, which was still
running. From the order desk's view: "I connected, sent the request, and got cut off," which
is indistinguishable from a slow network. Real load balancers and proxies hide crashes the
same way.

### Results

| | Value |
|---|---|
| Crash window | 22:58:19 to 22:58:50 UTC (+ ~8 s restart) |
| Failed requests | 319 |
| Marked "could not connect" | **0** (the prediction was right: the proxy masked it) |
| Marked PAYMENT_UNKNOWN | **319** |

### Reconciliation found a surprise

| Outcome | Orders |
|---|---|
| Actually charged → CONFIRMED | **220** |
| Not charged → FAILED | **99** |

Even though the cashier "crashed," **220 customers were actually charged.** The most likely
explanation: requests caught mid-flight during shutdown and restart, where the payment was
saved but the reply never made it back. Any rule like "service down = customer not charged"
would have been wrong for 220 people. The reconciliation job, which checks the real payment
records instead of guessing, got every one of them right.

---

## What I learned

1. **The obvious suspect isn't always guilty.** A deploy right before an outage looks guilty,
   but exact timestamps proved it innocent in Incident A.
2. **Fast failures and slow failures have different causes.** Instant errors pointed to
   rejections and connection problems; slow responses pointed to an overloaded database.
3. **No errors doesn't mean healthy.** The worst incident (41× slower) had zero errors.
4. **Averages hide incidents.** A 72-second outage looked like "99.86% success" over 3 minutes.
5. **A timeout means "unknown," not "failed."** Every timed-out payment I checked had
   actually been charged.
6. **Fixes can create new bugs.** The connection-pool fix introduced the stuck-order bug.
7. **Your monitoring can fail too,** usually at the worst possible moment.

---

## What this means for the AI investigator (next stage)

Each incident becomes a **test case** with a known correct answer. The AI agent will get
access to the same evidence I used (metrics, traces, logs, deployment history, and code
changes) and must reach the right conclusion:

| Scenario | Correct answer the AI must reach | Trap it must avoid |
|---|---|---|
| Bad deploy | Commit `8e9ac25` dropped an index; roll back | Blaming the database itself |
| Slow network | Payment latency; **not** a deploy | Blaming deploy #6, which happened minutes earlier |
| Crash | Payment unavailable; reconcile unknown orders | Assuming "crash = nobody was charged" |
| Sold out | Stock exhausted; not a system fault | Blaming the deploy that happened at the same time |

Measuring how often the AI gets these right is what will make this project credible.

---

## Deployment history (Day 2)

| # | Commit | Change |
|---|---|---|
| 1 | `3698894` | Load testing + deployment tracking |
| 2 | `010b360` | Feature: idempotent stock reservations |
| 3 | `8e9ac25` | **Bad change:** dropped the reservations index |
| 4 | `09ccca9` | Fix: pooled HTTP client (port exhaustion) |
| 5 | `c0e5958` | **Rollback** of #3 |
| 6 | `de14693` | Route payment traffic through Toxiproxy |
| 7 | `5d31f5e` | Fix: handle all errors; PAYMENT_UNKNOWN status |
