# Day 4 Report: The AI Investigator Goes Live

> **Incident Lab reports:** [Project overview](../README.md) · [Day 1: Services & monitoring](day-1-services-and-observability.md) · [Day 2: Breaking things on purpose](day-2-incidents.md) · [Day 3: The AI's investigation tools](day-3-investigator-tools.md) · [Day 4: The AI investigator goes live](day-4-ai-agent.md)
>
> **Who this is for:** anyone, technical or not. Each section starts with a plain-English explanation, then gives the technical detail for engineers.

## The short version

- I connected an AI model (Google Gemini) to the 8 investigation tools from Day 3. Now you can type
  a complaint like *"checkout is slow and some orders fail"*, and the AI investigates on its own:
  it decides what to check, reads the evidence, and writes a root-cause report.
- **Test 1, healthy system:** the AI correctly said "no incident found" and backed it with exact
  numbers (28,205 orders reported = 28,205 orders sent). Many AI demos fail here by inventing problems.
- **Test 2, a live network slowdown:** the first attempt was **partly wrong**. It blamed the payment
  service for an "outage" when the service was healthy and only the network to it was slow. I
  verified this myself and proved the AI wrong with three independent pieces of evidence.
- I improved the agent with **general troubleshooting rules** (not hints about this incident),
  hit Google's free-tier limit of **20 requests per day**, and redesigned the agent to need fewer requests.
- **Test 3, the same slowdown again:** the AI found the **correct root cause**, explained the decisive
  evidence (the payment service answered in 0.28 seconds while its caller waited over 3 seconds),
  and ruled out four other explanations.
- Honest caveat: the AI improved after changes I made while looking at this exact incident, so the
  real test is still ahead (Day 6), on incidents it was not tuned for.

---

## In plain English: what is an "AI agent"?

A normal chatbot answers from what it already knows. An **agent** can also **take actions** to
gather new information, then decide what to do next based on what it found.

Think of a detective who can't leave the office but has an assistant. The detective says
"get me the error logs from the warehouse," reads them, then says "now show me what was deployed
today," and so on, until there's enough evidence to name the cause. The AI is the detective; the
8 read-only tools from Day 3 are the assistant.

```
You: "Customers say checkout is slow and some orders fail"
  │
  ▼
Code gathers the basics automatically (no AI needed): service health, recent deploys,
order outcomes, error logs
  │
  ▼
AI reads them ──▶ "Payment calls are failing. Let me look at timings."  ──▶ asks for 2-4 tools
  ▲                                                                            │
  └────────────────────── results go back to the AI ◀──────────────────────────┘
  │   (repeats a few times, maximum 8 rounds)
  ▼
AI writes the report: summary, root cause, confidence, evidence, timeline,
customer impact, what it ruled out, recommended actions (which a human must approve)
```

---

## How it's built

| Piece | What it does |
|---|---|
| **System prompt** | The AI's job description: how the system is built, a step-by-step troubleshooting method, and rules like "every claim must quote a number or timestamp from a tool." |
| **Tool calling** | The AI is given the 8 tools' descriptions in a standard format (JSON Schema). It answers either "call these tools with these inputs" or with its final report. |
| **Automatic triage** | Evidence every investigation needs is collected by plain code before the AI starts, so it costs no AI requests. |
| **Structured report** | The AI must answer in a fixed JSON format, so the report can be displayed, stored, and later **scored automatically**. |
| **Saved records** | Every investigation is saved as a file in [`investigations/`](../investigations/): every tool call, how long it took, how many AI requests, and how many tokens were used. |
| **Safety** | The tools are read-only. The AI can recommend actions but can't perform them; every action requires human approval. |

Code: [`investigator/investigator/agent.py`](../investigator/investigator/agent.py) (the loop) and
[`gemini.py`](../investigator/investigator/gemini.py) (the connection to Google's API).

### The troubleshooting method the AI follows

1. Read the triage: what's abnormal, and when did it start?
2. Build a timeline.
3. Check what changed. **A deploy can only be the cause if it happened before the problem started**
   (the lesson from Day 2).
4. Gather supporting evidence: logs, request timelines, metrics.
5. Check what happened to customers.
6. Consider at least one alternative explanation and test it against the evidence.

---

## Choosing and connecting the AI model

**Model:** Google Gemini, used through its **free tier** to keep the project at $0.

| Decision | Why |
|---|---|
| Gemini instead of a model running on my laptop | Accuracy at multi-step reasoning matters most; small local models often lose track across many steps. (A local option can be added later.) |
| A "Flash" model | Fast, and good at tool calling. |
| Plain HTTP instead of Google's software kit | Every request and response is easy to inspect and debug. |
| No hints about my incidents in the instructions | Otherwise, measuring accuracy later would be meaningless. |

**Keeping the API key secret:** the key lives in a `.env` file that Git is told to ignore
(checked with `git check-ignore`). It was moved from the clipboard into the file with `pbpaste`,
so it was never typed, displayed, or pasted anywhere. `docker-compose.yml` only contains a placeholder.

**Real-world surprises while connecting:**
- `gemini-2.5-flash` is **no longer available to new accounts**; Google's error message pointed to a newer model.
- The name `gemini-3.5-flash` was quietly served by `gemini-3.6-flash`.
- The free tier allows **20 requests per day per model** (more on this below).
- On the free tier, Google may use inputs to improve its models, which is fine for fake lab data
  but a reason never to send real customer data through a free tier.

---

## Test 1: Is the AI honest when nothing is wrong?

**Setup:** 30 seconds of normal traffic, then the question *"Is the order system healthy right now?"*

**Result:** ✅ **"No incident found," high confidence.**

| AI's claim | Reality |
|---|---|
| 28,205 orders confirmed | Load test sent exactly 28,205 ✓ |
| 0 errors; 0 failed, stuck, or unknown orders | 0 failures ✓ |
| No deploys in the last hour | Last deploy was two weeks earlier ✓ |
| No invented problems | Ignored old deploys and harmless warnings ✓ |

**Why this matters:** an AI that "finds" problems in a healthy system wastes engineers' time and
quickly loses their trust. Saying "all clear" when it's true is a core requirement.

---

## Test 2: A live incident, and the AI was partly wrong

**Setup:** 20 simulated customers ordering non-stop. Then I added 2.5 seconds (± 1 second) of
**network delay** between the order service and the payment service. The order service gives up
after 3 seconds. The AI was only told *"Customers are complaining that checkout is slow and some
orders fail."* It didn't know what I had done.

### What it got right and wrong

| | AI said | Reality | |
|---|---|---|---|
| Was it a deploy? | No | Correct | ✅ |
| Which part of the system? | The payment path | Correct | ✅ |
| Error count | 207 "Payment outcome unknown" errors | Exactly 207 ✓ | ✅ |
| Recommended reconciliation + circuit breaker | Yes | Both appropriate | ✅ |
| **Root cause** | "**payment-service outage**" | **Network delay**; the payment service was healthy | ❌ |
| "20 orders stuck" | Stuck | The 20 orders currently being processed (one per simulated customer) | ❌ |

### How I proved the AI wrong

Its main evidence was a monitoring signal called `up` dropping to 0, which it read as "the service
went down." I checked three things myself:

1. **Docker:** the payment service had been running for 5 days with **0 restarts**. It never went down.
2. **The `up` signal:** 97.2% normal over 30 minutes. The monitoring system failed to collect data
   for **less than a minute**. That means "couldn't take a reading," not "service dead."
   (Why those readings failed is still unexplained; my guess is the laptop being overloaded.)
3. **The money:** the reconciliation job found that **all 207** uncertain orders had actually been
   charged. A crashed payment service can't record charges.

**The mistake in its reasoning:** it built a conclusion on one signal and never made the decisive
comparison: *how long did the caller wait vs. how long did the payment service take?* If the caller
waits seconds but the service answers in milliseconds, the time is lost **between** them.

An on-call engineer following the first report would have investigated a healthy service and lost
valuable time. **This is why AI conclusions need verification, and why this project measures accuracy.**

---

## Improving the agent with general rules

Each fix is a general troubleshooting principle, not a hint about this specific incident:

| Problem in its reasoning | Fix |
|---|---|
| Treated "couldn't collect a reading" as "service is down" | Tool notes now explain what `up = 0` really means. New rule: before calling a service dead, check whether it is still doing work. |
| Never compared the caller's wait time with the callee's response time | New rule plus a tool note: a big gap between them means time is lost in the network in between. |
| Called normal in-progress orders "stuck" | The order tool now reports `stuck_pending_orders` (pending for over 30 seconds) separately. |
| Couldn't see **when** a metric was at its lowest | Metric summaries now include `lowest_at`. |

---

## Hitting the free-tier limit, and redesigning around it

The next run never started. Google refused every request. Reading Google's actual error message
(instead of guessing) showed:

> Quota exceeded ... `GenerateRequestsPerDayPerProjectPerModel-FreeTier` ... limit: **20** ... retry in **4h35m**

The first two investigations used about 11–12 AI requests each, plus retries. 20 per day runs out fast.

**The redesign:**

| Change | Effect |
|---|---|
| **Automatic triage** | The 6 tool calls every investigation needs are made by plain code before the AI starts: zero AI requests. |
| **Parallel tool calls** | The AI is told to ask for several independent tools in one round, instead of one per round. |
| **Round limit** | Aim for about 4 rounds, hard stop at 8. |
| **Fail fast** | If the *daily* limit is hit, stop immediately with a clear message (instead of retrying for minutes). |
| **Honor Google's retry time** | For per-minute limits, wait exactly as long as Google says. |
| **Request pacing** | At least 6 seconds between requests to stay under per-minute limits. |

Switching to `gemini-3.8-flash` (the model Google recommended) also gave a fresh daily quota,
since limits are counted per model.

---

## Test 3: The same incident again, and this time it was right

**Result:** ✅ **Correct root cause, high confidence.**

> *"Network latency / jitter introduced by toxiproxy between order-service and payment-service
> exceeds the order-service HTTP client timeout of 3.0 seconds."*

| | Test 2 | **Test 3** |
|---|---|---|
| Root cause | ❌ Payment service outage | ✅ **Network delay between the services** |
| Decisive evidence | One failed monitoring reading | ✅ **Payment service answered in ≤ 0.28 s; the order service waited 3.01–3.16 s** |
| Ruled out | Deploys | ✅ Deploys, payment service failure, database pool, inventory |
| "Stuck" orders mistake | ❌ | ✅ Not repeated |
| Recommended fix | Check the payment service (wrong place) | ✅ Remove the network delay, reconcile orders, review timeouts |

It also noticed something I didn't point out: **two separate waves of errors**, one from the run
where the AI was blocked by the quota, and the current one. That's correct.

**Cross-check:** the load test had **198 failed orders**; reconciliation found **198** uncertain
payments, and all 198 customers had actually been charged.

### What still needs work

- **It went in circles for 4 rounds** looking for proxy and "latency" metrics that don't exist,
  then hit the round limit. Fix for later: tell the AI which metrics exist.
- **Tokens went up, not down** (118K vs 69K). Fewer AI requests, but each request resends the whole
  conversation, including the large triage block. Fewer calls doesn't automatically mean cheaper.
- **One weak piece of evidence:** an *average* latency of 16.92 ms, diluted by thousands of fast
  requests. The *maximum* it found later (3.01–3.16 s) was the real evidence.

---

## All runs at a glance

| Run | Model | Scenario | Result | AI requests | Tool calls | Time | Tokens |
|---|---|---|---|---|---|---|---|
| 1 | Gemini 3.5 Flash | Healthy system | ✅ Correct | ~11 | 11 | 109 s | 55,702 |
| 2 | Gemini 3.5 Flash | Network delay | ⚠️ Partly correct | ~12 | 12 | 269 s* | 68,920 |
| — | Gemini 3.5 Flash | Network delay | ⛔ Blocked by daily quota | 0 | 0 | — | — |
| 3 | Gemini 3.8 Flash | Network delay | ✅ Correct | 9 | 24 (6 triage) | 70 s | 118,453 |

\* Mostly waiting on Google's rate limits.

---

## Honest caveats

1. **Two things changed between Test 2 and Test 3:** the reasoning rules *and* the model. I can't
   say which one fixed the diagnosis; probably both contributed.
2. **The rules were written after studying this exact incident.** A re-test on the same incident
   favors the agent. The fair test is Day 6, with incidents it wasn't tuned on (the bad deploy and the crash).
3. **One run each.** AI models can answer differently each time, so single runs prove possibility,
   not reliability. Day 6 will run each scenario several times.

---

## What I learned

1. **Verify AI conclusions.** The first wrong answer sounded confident and well-written.
2. **Test the "nothing is wrong" case.** An investigator that invents problems is worse than none.
3. **Know what each signal really means.** "Couldn't take a reading" is not "service is down."
4. **Locate latency by comparing both sides** of a call.
5. **Read the actual error message.** Guessing about the quota problem would have wasted hours; Google's message stated the exact limit and reset time.
6. **Real constraints shape design.** A 20-requests-per-day limit led to a better architecture: deterministic code for routine steps, AI only for judgment.

---

## Glossary (plain English)

| Term | Meaning |
|---|---|
| **LLM** | Large language model: the kind of AI behind tools like Gemini, Claude, and ChatGPT. |
| **Agent** | An AI that can take actions (here, calling tools) and decide its next step from the results. |
| **System prompt** | Standing instructions given to the AI before the conversation: its role, method, and rules. |
| **Tool / function calling** | The AI asks the program to run a specific tool with specific inputs, then reads the result. |
| **Triage** | The first quick checks done for every problem, like a nurse taking vital signs. |
| **Token** | The unit AI models read and are billed by; roughly 4 characters. |
| **Rate limit / quota** | A cap on how many requests you can make per minute or per day. |
| **HTTP 429** | The standard error code for "too many requests." |
| **Thought signature** | An encrypted record of the model's internal reasoning that must be sent back unchanged between steps. |
| **Reconciliation** | Settling uncertain orders by checking the payment records, the source of truth. |
| **Root cause** | The underlying reason for a problem, as opposed to its symptoms (slowness and errors are symptoms). |

---

## How to run it yourself

```bash
# one-time: put a Gemini API key in .env (never commit it)
echo ".env" >> .gitignore
printf 'GEMINI_API_KEY=%s\n' "$(pbpaste)" > .env
echo "GEMINI_MODEL=gemini-3.8-flash" >> .env

# investigate
./scripts/investigate.sh "Routine check: is the order system healthy right now?" 10
./scripts/investigate.sh "Customers say checkout is slow and some orders fail" 5
```

Every investigation is saved in [`investigations/`](../investigations/).

---

## What happens next

- **Day 5:** a web dashboard: service health at a glance, an "Investigate" button, the AI's steps
  shown live, and a human-approval step for any recommended action.
- **Day 6:** evaluation: run every incident from the [Day 2 report](day-2-incidents.md) several
  times, including ones the agent was never tuned on, and measure how often it finds the right
  root cause, how fast, and at what cost.
