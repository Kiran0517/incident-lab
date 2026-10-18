"""The investigation agent: an LLM that calls the read-only tools step by step,
then writes a structured root-cause report backed by evidence.

Loop:  problem -> model picks a tool -> tool runs -> result goes back to the model -> ...
       until the model answers with a final JSON report (or the step limit is reached).
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from .gemini import GeminiClient, clean_schema
from .registry import TOOLS, call_tool

MAX_RESULT_CHARS = 12000
INVESTIGATIONS_DIR = os.getenv("INVESTIGATIONS_DIR", "/app/investigations")

SYSTEM_PROMPT = """You are an experienced site reliability engineer investigating a production incident.

The system is an e-commerce backend with three Spring Boot services sharing one PostgreSQL database:
- order-service (entry point, POST /orders) creates the order, then calls
- inventory-service (POST /inventory/reserve) to reserve stock, then calls
- payment-service (POST /payments) through a network proxy named "toxiproxy".

You can only observe the system through the provided tools. They are read-only.

Method:
1. Start with get_service_overview to see what is abnormal and when it started.
2. Build a timeline: when did the problem start, and is it still happening?
3. Check what changed with get_recent_deployments. A deployment can only be the cause if it happened
   BEFORE the problem started and its change plausibly explains the symptoms. If you suspect one,
   read its diff with get_commit_diff.
4. Gather supporting evidence: search_logs (ERROR and WARN), find_traces (use min_duration_ms when
   looking for slowness), get_trace on one representative request, query_metrics for anything else.
5. Check customer impact with get_order_outcomes.
6. Before concluding, consider at least one alternative explanation and test it against the evidence.

Rules:
- Every claim must come from tool output. Quote specific numbers, timestamps, and names.
- Distinguish symptoms (high latency, errors) from causes.
- Business outcomes (orders rejected for unknown products or insufficient stock) are not system faults.
- An isolated warning that does not line up in time and mechanism with the symptoms is noise.
- Before concluding that a service is down, check whether it is still doing its work (its request rate,
  its logs, orders completing). A slow or unreachable path is different from a dead service.
- When latency is the symptom, locate it: compare how long the caller waits with how long the callee
  itself takes. The difference is time spent between them.
- Prefer the explanation that accounts for ALL the evidence, including evidence that contradicts your
  first idea. Read the "notes" that tools return; they explain how to interpret each field.
- Efficiency: search ERROR logs first; look at WARN or other filters only if needed.
- If the evidence is insufficient, say so and use low confidence instead of guessing.
- If everything looks healthy, say so.
- Be efficient: usually 4 to 10 tool calls.

When you are done, reply with ONLY a JSON object, no other text:
{
  "summary": "2-3 sentences in plain English that a non-technical person understands",
  "root_cause": "the specific cause, or 'insufficient evidence', or 'no incident found'",
  "confidence": "high | medium | low",
  "evidence": [{"source": "tool name", "finding": "specific fact with numbers and timestamps"}],
  "timeline": ["HH:MM:SS UTC - event"],
  "customer_impact": "what happened to orders and customers, with numbers",
  "ruled_out": ["an alternative explanation and why the evidence rejects it"],
  "recommended_actions": ["most urgent first; all actions require human approval"]
}"""


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _declarations() -> list:
    return [
        {"name": name, "description": tool["description"], "parameters": clean_schema(tool["parameters"])}
        for name, tool in TOOLS.items()
    ]


def _parse_report(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _save(record: dict) -> str:
    os.makedirs(INVESTIGATIONS_DIR, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", record["problem"].lower()).strip("-")[:40] or "investigation"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(INVESTIGATIONS_DIR, f"{stamp}-{slug}.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    return path


def investigate(problem: str, minutes: int = 15, max_steps: int = 12) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Add it to the .env file in the project root.")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    client = GeminiClient(api_key, model)
    declarations = _declarations()

    started = time.time()
    now = datetime.now(timezone.utc)
    contents = [{"role": "user", "parts": [{"text": (
        f"Current time (UTC): {now.isoformat(timespec='seconds')}\n"
        f"Reported problem: {problem}\n"
        f"Investigate the last {minutes} minutes unless the evidence points further back."
    )}]}]

    steps = []
    usage = {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    final_text = ""
    _log(f"Investigating with {model} ...")

    for step in range(1, max_steps + 2):
        allow_tools = step <= max_steps
        if not allow_tools:
            contents.append({"role": "user", "parts": [{"text": (
                "Step limit reached. Do not call more tools. Give your final JSON report now, "
                "based on the evidence gathered so far.")}]})

        response = client.generate(SYSTEM_PROMPT, contents, declarations, allow_tools=allow_tools)
        meta = response.get("usageMetadata", {})
        usage["prompt_tokens"] += meta.get("promptTokenCount", 0)
        usage["output_tokens"] += meta.get("candidatesTokenCount", 0) + meta.get("thoughtsTokenCount", 0)
        usage["total_tokens"] += meta.get("totalTokenCount", 0)

        candidates = response.get("candidates") or []
        if not candidates or "content" not in candidates[0]:
            raise RuntimeError(f"Model returned no content: {json.dumps(response)[:500]}")
        content = candidates[0]["content"]
        contents.append(content)  # keep the model's turn exactly as returned

        parts = content.get("parts", [])
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            final_text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            break

        replies = []
        for call in calls:
            name, args = call.get("name"), call.get("args") or {}
            _log(f"  step {step}: {name} {json.dumps(args)}")
            t0 = time.time()
            result = call_tool(name, args)
            text = json.dumps(result, default=str)
            truncated = len(text) > MAX_RESULT_CHARS
            if truncated:
                result = {"truncated": True, "partial_result": text[:MAX_RESULT_CHARS]}
            steps.append({
                "step": step, "tool": name, "args": args,
                "seconds": round(time.time() - t0, 2), "result_chars": len(text),
                "truncated": truncated,
                "error": result.get("error") if isinstance(result, dict) else None,
            })
            replies.append({"functionResponse": {"name": name, "response": result}})
        contents.append({"role": "user", "parts": replies})

    report = _parse_report(final_text)
    record = {
        "problem": problem,
        "window_minutes": minutes,
        "model": model,
        "started_at": now.isoformat(timespec="seconds"),
        "duration_seconds": round(time.time() - started, 1),
        "tool_calls": len(steps),
        "usage": usage,
        "steps": steps,
        "report": report,
        "raw_final_text": None if report else final_text,
    }
    record["saved_to"] = _save(record)
    return record


def format_report(record: dict) -> str:
    r = record.get("report")
    head = (f"Problem: {record['problem']}\n"
            f"Model: {record['model']} | {record['tool_calls']} tool calls | "
            f"{record['duration_seconds']}s | {record['usage']['total_tokens']} tokens")
    if not r:
        return f"{head}\n\nCould not parse a structured report. Raw answer:\n{record.get('raw_final_text')}"

    def items(key):
        out = []
        for item in r.get(key) or []:
            if isinstance(item, dict):
                out.append(f"  - [{item.get('source', '?')}] {item.get('finding', item)}")
            else:
                out.append(f"  - {item}")
        return out or ["  (none)"]

    lines = ["=" * 72, "INCIDENT INVESTIGATION REPORT", "=" * 72, head, "",
             "SUMMARY", f"  {r.get('summary', '')}", "",
             f"ROOT CAUSE  (confidence: {r.get('confidence', '?')})", f"  {r.get('root_cause', '')}", "",
             "EVIDENCE", *items("evidence"), "",
             "TIMELINE", *items("timeline"), "",
             "CUSTOMER IMPACT", f"  {r.get('customer_impact', '')}", "",
             "RULED OUT", *items("ruled_out"), "",
             "RECOMMENDED ACTIONS (require human approval)", *items("recommended_actions"), "",
             f"Full record saved to: {record.get('saved_to')}"]
    return "\n".join(lines)
