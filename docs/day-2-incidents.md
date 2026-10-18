# Day 2: Breaking things on purpose

[Overview](../README.md) · [Day 1](day-1-services-and-observability.md) · [Day 2](day-2-incidents.md) · [Day 3](day-3-investigator-tools.md) · [Day 4](day-4-ai-agent.md)

## Summary

I injected three failures into the system while 20 simulated customers were ordering continuously: a bad deploy, network latency between two services, and a crashed payment service. Along the way the system also failed in four ways I didn't plan for, and those turned out to be the most useful findings. The biggest one: when a payment call times out, you don't actually know whether the customer was charged. In every case I checked, they had been.

Each incident below is written up like a short postmortem: what happened, the impact, the cause, the fix, and what I took away from it. All numbers are from actual runs.

## Overview

| # | Incident | Planned | Impact | Cause | Fixed |
|---|---|---|---|---|---|
| A1 | Store sold out | No | Orders rejected | Test data ran out | Restocked |
| A2 | Jaeger crashed | No | Lost tracing | Unbounded in-memory storage | Yes |
| A3 | order-service couldn't open connections | No | ~41,000 failed orders | Ephemeral port exhaustion | Yes |
| 1 | Bad deploy | Yes | 41x drop in throughput | Dropped database index | Rolled back |
| 2 | Latency to payment | Yes | 119 customers charged, orders stuck | Unhandled exception type | Yes |
| 3 | Payment service crash | Yes | 319 orders in unknown state | Crash masked by the proxy | Reconciled |

## Baseline

Before breaking anything, I measured normal behavior with k6 (20 virtual users ordering non-stop):

| Metric | Value |
|---|---|
| Throughput | ~1,200 orders/sec |
| p95 latency | ~45 ms |
| Success rate | 100% |

p95 means 95% of requests finished at least that fast. It's more useful than an average, because averages hide the slow requests that customers actually notice.

## Incident A: the test that went wrong in three ways I didn't expect

The plan was to ship a bad deploy while traffic was flowing. Instead, 67% of orders failed, and they failed *fast*, which didn't fit a slow system at all. When the evidence doesn't fit the theory, the theory is wrong, so I rebuilt the timeline from the database.

| Time (UTC) | What happened | Evidence |
|---|---|---|
| 22:03 | Load test starts | 119,407 confirmed orders that minute |
| 22:04 | Store sells out | Stock = 0 for every SKU; 82,183 rejections |
| ~22:04 | Jaeger crashes | Container exited with code 137 (killed for memory) |
| 22:05–22:06 | order-service can't open connections | ~41,000 failures with `Cannot assign requested address` |
| ~22:07 | Load test ends | |
| 22:07:56 | Bad deploy goes out | Deployments table |

The deploy happened *after* the traffic stopped. It caused none of this, even though it was the obvious suspect. Without exact timestamps I would have blamed it.

**A1, sold out.** Each product started with 100,000 units. Earlier runs sold about 94,000 and this one sold the remaining 206,011, which adds up to the full 300,000. Rejections are fast, which explains the instant failures. I restocked to 10 million per product.

**A2, Jaeger out of memory.** Jaeger's all-in-one image keeps every trace in memory with no limit. Around 600,000 requests at ten spans each was enough for the OS to kill it. That's a real problem, since monitoring tends to fall over exactly when traffic is highest. I capped it at the newest 50,000 traces.

**A3, port exhaustion.** Every outgoing connection needs a local port, and there are only about 28,000 of them. After a connection closes, its port sits in TIME_WAIT for roughly a minute before it can be reused. The HTTP client I started with (`HttpURLConnection`) only keeps a handful of idle connections per host, so at about 2,600 requests/sec it kept opening new connections faster than ports were freed, until none were left. I switched to the JDK `HttpClient`, which pools and reuses connections.

## Incident 1: a "harmless" cleanup that made the store 41x slower

The day before, I added an idempotency check to inventory: before reserving stock, it checks whether this order already has a reservation, so a retried request can't reserve twice. The check is fast because `reservations.order_ref` is indexed.

Then I shipped a commit titled *"drop unused index to reduce write overhead."* Teams make changes like this all the time. The index wasn't unused, though, and without it every order made PostgreSQL scan all 3 million reservation rows.

| Metric | Before | After the deploy |
|---|---|---|
| Single order, no load | 0.012 s | 0.550 s |
| Throughput under load | 1,197/s | 29/s |
| p95 latency | 45 ms | 1,040 ms |
| Error rate | 0% | 0% |

The part I find most interesting is that last row. Nothing technically failed. Every order eventually went through and health checks stayed green, but in practice customers would have given up long before a checkout took a second. Only latency and throughput showed the problem; error-based alerting would never have fired.

**How the evidence pointed to the cause:**

1. `EXPLAIN ANALYZE` showed a parallel sequential scan taking 1,232 ms instead of an index lookup.
2. HikariCP metrics showed inventory's 10 connections pinned at 10/10 with requests queuing, because each slow query held a connection for about half a second.
3. The deployments table showed the slowdown started right after deploy #3 (commit `8e9ac25`).

The chain is a common one: missing index, slow query, connections held longer, pool exhausted, requests queue, latency explodes.

**Fix.** I rolled back first and investigated second, using `git revert` so the history keeps both the mistake and the fix (commit `c0e5958`). Throughput recovered to 1,227/s with p95 at 36.8 ms. To prevent this in a real codebase, I'd check query plans in CI, alert on p95 instead of only errors, and look at `pg_stat_user_indexes` before dropping any index.

## Incident 2: slow network, and customers charged for orders that never completed

No code change this time. I used Toxiproxy to add 2.5 s (± 1 s) of latency to payment-service's responses. order-service gives up after 3 seconds.

I expected the slow orders to end up `FAILED`. Instead, 119 orders were stuck in `PENDING` with no log line at all. When I checked further, all 119 had both a stock reservation and a captured payment. Those customers were charged, saw an error, and had orders that would never complete.

**Cause.** When the 3-second timeout fired, the JDK HttpClient (from the A3 fix) surfaced it as a `java.util.concurrent.CancellationException`. My handler only caught `RestClientException`, so this one went straight past it: no status update, no log. A fix for one bug had created another.

**The more important lesson** is that even if the exception had been caught, `FAILED` would have been the wrong status. The payment had gone through and only the reply was slow. After a timeout you don't know the outcome, and the honest status is "unknown." Payment APIs like Stripe's are designed around this with idempotency keys.

**Fix** (commit `5d31f5e`):

1. Catch every exception on the downstream calls, so no order can be left silently stuck.
2. Separate "definitely failed" from "unknown." If the connection was refused, payment never got the request, so the order is `FAILED`. If the request was sent and then timed out, the order is `PAYMENT_UNKNOWN`.
3. A reconciliation job (`scripts/reconcile.sh`) settles unknown orders against the payments table: a payment exists, so the order is `CONFIRMED`; no payment, so it's `FAILED`.

Re-running the same incident after the fix:

| | Before | After |
|---|---|---|
| Orders stuck in PENDING | 119 | 0 |
| Orders marked PAYMENT_UNKNOWN | 0 | 45 |
| Matching log lines | 0 | 45 |

Reconciliation then resolved all 164 uncertain orders (119 old and 45 new), and every one of them had been charged. Marking them failed would have told 164 paying customers their order didn't go through, and some of them would have ordered again.

I also checked that the last deploy (#6, at 22:43:29) wasn't involved. Traffic ran cleanly from about 22:46:40 until I injected the latency at 22:47:39.

## Incident 3: payment service crash

I stopped payment-service for about 30 seconds while orders were flowing.

Before running it, I expected these orders would *not* be marked `FAILED`. order-service doesn't talk to payment-service directly; it talks to Toxiproxy, which was still up. From order-service's side, it connected, sent the request, and got cut off, which looks exactly like a timeout. Load balancers and proxies hide crashes the same way.

| | Value |
|---|---|
| Crash window | 22:58:19 to 22:58:50 UTC, plus ~8 s to restart |
| Failed requests | 319 |
| Marked "could not connect" | 0 |
| Marked PAYMENT_UNKNOWN | 319 |

Reconciliation then found 220 of those customers had been charged and 99 hadn't. Even with the service "down," most of the in-flight requests had already been processed; my best explanation is requests caught mid-shutdown and mid-restart, where the charge was saved but the response never made it back. A rule like "service down means no charge" would have been wrong for 220 people.

## What I took away from this

- The obvious suspect isn't always guilty. Exact timestamps cleared the deploy in Incident A.
- Fast failures and slow failures usually have different causes.
- Zero errors doesn't mean healthy. The worst incident here had none.
- Averages hide incidents. A 72-second outage looked like 99.86% success over a 3-minute run.
- A timeout means "unknown," not "failed."
- Fixes can introduce new bugs, and re-running the same failure test is how you catch them.
- Monitoring can fail too, usually at the worst moment.

## Deploy history

| # | Commit | Change |
|---|---|---|
| 1 | `3698894` | Load testing and deploy tracking |
| 2 | `010b360` | Idempotent stock reservations |
| 3 | `8e9ac25` | Dropped the reservations index (the bad deploy) |
| 4 | `09ccca9` | Pooled HTTP client (port exhaustion fix) |
| 5 | `c0e5958` | Rollback of #3 |
| 6 | `de14693` | Routed payment traffic through Toxiproxy |
| 7 | `5d31f5e` | Catch all downstream errors; PAYMENT_UNKNOWN status |

## Next

These incidents become the test cases for the AI agent, since the correct answers are known. On Day 3 I built the tools it uses to look at the system. Continue with [Day 3](day-3-investigator-tools.md).
