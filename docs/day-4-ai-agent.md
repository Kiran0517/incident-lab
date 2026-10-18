# Day 4: The agent goes live

[Overview](../README.md) · [Day 1](day-1-services-and-observability.md) · [Day 2](day-2-incidents.md) · [Day 3](day-3-investigator-tools.md) · [Day 4](day-4-ai-agent.md)

## Summary

I connected Gemini to the eight tools from Day 3. You give it a complaint like *"checkout is slow and some orders fail,"* and it decides what to look at, reads the evidence, and writes a root-cause report.

It handled a healthy system correctly. On its first live incident (network latency between order-service and payment-service), it got the area right but the mechanism wrong: it blamed a payment-service outage when the service was fine and only the network to it was slow. I proved that with three independent checks, gave it some general troubleshooting rules, ran into the free tier's limit of 20 requests per day, redesigned the agent to use fewer requests, and re-ran it. The second time it found the actual cause and showed the evidence for it.

The caveat is that I tuned it while looking at this same incident, so it hasn't been tested fairly yet. That's what Day 6 is for.

## How it works

An agent differs from a regular chatbot in that it can take actions to collect information and then decide what to do next based on what comes back.

```
Problem description
   │
   ▼
Triage: plain code collects service health, recent deploys, order outcomes,
        and ERROR logs for every service (no model calls)
   │
   ▼
Model reads the evidence ──▶ asks for 1-4 tool calls ──▶ tools run
   ▲                                                       │
   └──────────────────── results go back ◀─────────────────┘
   │   (up to 8 rounds)
   ▼
Report: summary, root cause, confidence, evidence, timeline,
        customer impact, what was ruled out, recommended actions
```

The pieces:

- **System prompt.** Describes the system, a troubleshooting method, and rules, for example "every claim must cite a number or timestamp from a tool."
- **Function calling.** The model gets the tool schemas and replies either with tool calls or with its final answer.
- **Structured output.** The final report has to be JSON in a fixed shape, so it can be displayed, stored, and eventually scored automatically.
- **Records.** Every run is saved to [`investigations/`](../investigations/) with each tool call, its duration, the number of model calls, and token usage.
- **Safety.** The tools are read-only. The agent can recommend actions, but a human has to carry them out.

The method in the prompt is roughly what I'd do myself: read the triage, figure out when the problem started, check what changed (and only treat a deploy as a suspect if it happened before the problem started), gather supporting evidence, check customer impact, and test at least one alternative explanation before concluding.

I deliberately kept anything about my specific incidents out of the prompt. If the prompt contained the answers, measuring accuracy later would be pointless.

Code: [`agent.py`](../investigator/investigator/agent.py) and [`gemini.py`](../investigator/investigator/gemini.py).

## Model and setup

I used Gemini through its free tier to keep the project at zero cost, calling the REST API directly instead of using the SDK so every request and response is easy to inspect. A local model was an option, but small local models tend to lose track over multi-step tool use, and accuracy matters most here.

The API key lives in `.env`, which is in `.gitignore` (I confirmed with `git check-ignore`). I wrote it into the file straight from the clipboard with `pbpaste`, so it was never typed or displayed. `docker-compose.yml` only references `${GEMINI_API_KEY}`.

A few things I didn't expect:

- `gemini-2.5-flash` is no longer available to new accounts; the 404 response pointed to a newer model.
- Requests to `gemini-3.5-flash` were counted against `gemini-3.6-flash`'s quota, so the name is redirected.
- The free tier allows 20 requests per day per model.
- On the free tier, Google may use inputs to improve its models. That's fine for synthetic lab data, but it's a reason not to send real customer data through it.

## Test 1: healthy system

After 30 seconds of normal traffic, I asked: *"Is the order system healthy right now?"*

It answered "no incident found" with high confidence, and the evidence checked out:

| Agent's claim | Actual |
|---|---|
| 28,205 orders confirmed | k6 sent 28,205 |
| No errors; no failed, stuck, or unknown orders | k6 saw 0 failures |
| No deploys in the last hour | The last deploy was two weeks earlier |

This case matters more than it looks. An agent that finds problems in a healthy system wastes people's time and loses their trust fast.

## Test 2: live latency incident (partly wrong)

With 20 virtual users running, I added 2.5 s (± 1 s) of latency between order-service and payment-service through Toxiproxy. order-service times out after 3 s. The agent only got the complaint: *"Customers are complaining that checkout is slow and some orders fail."*

| | Agent said | Actual | |
|---|---|---|---|
| Deploy involved? | No | Correct | right |
| Which area? | Payment path | Correct | right |
| Errors | 207 "Payment outcome unknown" | Exactly 207 | right |
| Root cause | payment-service outage | Network latency; payment-service was healthy | wrong |
| "20 stuck orders" | Stuck | The 20 orders in flight, one per virtual user | wrong |

Its main evidence was the Prometheus `up` metric for payment-service dropping to 0, which it read as "the service went down." I checked three things:

1. **Docker:** payment-service had been running for five days with zero restarts.
2. **The metric itself:** `up` averaged 0.972 over 30 minutes. Prometheus failed to scrape it for under a minute, which means a scrape failed, not that the service died. I still don't know why those scrapes failed. My guess is the laptop being overloaded, but I haven't confirmed it.
3. **Payments:** reconciliation found that all 207 uncertain orders had been charged. A crashed service can't record charges.

The flaw in its reasoning was building the conclusion on one signal and never making the obvious comparison: how long the caller waited versus how long payment-service took to respond. If the caller waits seconds and the service answers in milliseconds, the time is going somewhere in between. Someone acting on that first report would have spent time digging into a healthy service.

## Changes after Test 2

I added general troubleshooting rules rather than hints about this incident:

| Problem | Change |
|---|---|
| Treated a failed scrape as an outage | Tool notes explain what `up = 0` means, and a new rule says to check whether a service is still doing work before calling it down |
| Never compared caller vs. callee latency | New rule and tool note: a large gap means time is being lost between them |
| Counted in-flight orders as stuck | `get_order_outcomes` now reports `stuck_pending_orders` (pending for more than 30 s) separately |
| Couldn't tell when a metric bottomed out | Metric summaries now include `lowest_at` |

## Hitting the quota

The next run didn't start. Every request came back 429, and the agent gave up after about three and a half minutes of retries. Rather than guess, I sent a single request with curl and read Google's error:

> Quota exceeded ... `GenerateRequestsPerDayPerProjectPerModel-FreeTier` ... limit: 20 ... retry in 4h35m

The first two runs had used 11 to 12 model calls each, plus retries, so 20 was gone quickly. I changed the design:

- **Triage in code.** The six tool calls every investigation starts with now run before the model is involved, at no cost against the quota.
- **Parallel tool calls.** The prompt asks the model to request independent tools in the same turn.
- **Round limit.** It aims for about 4 rounds, with a hard stop at 8.
- **Fail fast.** If the daily quota is exhausted, it stops right away with a clear message.
- **Honor `retryDelay`.** For per-minute limits, it waits as long as Google says to.
- **Pacing.** At least 6 seconds between requests.

I also switched to `gemini-3.8-flash`, the model Google's error message recommended. Quotas are per model, so that came with its own 20 requests.

## Test 3: same incident, correct diagnosis

> *"Network latency / jitter introduced by toxiproxy between order-service and payment-service exceeds the order-service HTTP client timeout of 3.0 seconds."*

This time the reasoning held up. It compared both sides of the call: payment-service's maximum server-side time was 0.28 s, while order-service's client waited 3.01–3.16 s. It ruled out a payment-service failure (no 5xx, all 201s), database pool exhaustion, inventory, and deploys, each with numbers. Its recommendation was to remove the latency on the proxy, reconcile the affected orders, and review the timeout policy. It also noticed two separate waves of errors, which was correct: one from the earlier run that hit the quota, and one from this run.

The counts matched again: k6 recorded 198 failed orders, reconciliation found 198 `PAYMENT_UNKNOWN`, and all 198 customers had been charged.

What still needs work:

- It spent four rounds looking for proxy and "latency" metrics that don't exist, then hit the round limit. Telling it which metrics are available should fix that.
- Token use went up, from 69K to 118K. It made fewer model calls, but every call resends the whole conversation, including the triage block. Fewer calls doesn't automatically mean cheaper.
- One piece of its evidence was weak: an *average* latency of 16.92 ms, pulled down by thousands of fast requests. The maximum it found later was the real signal.

## All runs

| Run | Model | Scenario | Result | Model calls | Tool calls | Time | Tokens |
|---|---|---|---|---|---|---|---|
| 1 | Gemini 3.5 Flash | Healthy | Correct | ~11 | 11 | 109 s | 55,702 |
| 2 | Gemini 3.5 Flash | Latency | Partly correct | ~12 | 12 | 269 s* | 68,920 |
| – | Gemini 3.5 Flash | Latency | Blocked by quota | 0 | 0 | – | – |
| 3 | Gemini 3.8 Flash | Latency | Correct | 9 | 24 (6 triage) | 70 s | 118,453 |

\* Most of this was waiting on rate limits.

## Caveats

1. Two things changed between Test 2 and Test 3: the reasoning rules and the model. I can't separate their effects.
2. The rules were written after studying this incident, so re-testing on it favors the agent. The fair test is on incidents it wasn't tuned for, like the bad deploy and the crash.
3. Each scenario ran once. LLM output varies between runs, so these results show the agent *can* get it right, not how often it does. Day 6 will run each scenario several times.

## What I learned

- Verify the agent's conclusions. The wrong answer read just as confidently as the right one.
- Test the case where nothing is wrong.
- Know exactly what a signal measures. A failed scrape is not a dead service.
- To locate latency, compare both ends of the call.
- Read the actual error message. The quota error said precisely what the limit was and when it would reset.
- The 20-request limit pushed the design somewhere better: deterministic code for routine steps, and the model only where judgment is needed.

## Running it

```bash
echo ".env" >> .gitignore
printf 'GEMINI_API_KEY=%s\n' "$(pbpaste)" > .env    # key copied to clipboard first
echo "GEMINI_MODEL=gemini-3.8-flash" >> .env

./scripts/investigate.sh "Routine check: is the order system healthy right now?" 10
./scripts/investigate.sh "Customers say checkout is slow and some orders fail" 5
```

## Next

Day 5 is a dashboard: service health at a glance, an "Investigate" button, the agent's steps as they happen, and an approval step for any action it recommends. Day 6 is the evaluation: every incident from [Day 2](day-2-incidents.md), run several times, including the ones the agent wasn't tuned on, measuring accuracy, time, and cost.
