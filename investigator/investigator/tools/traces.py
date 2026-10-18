"""Jaeger tools: find slow or failing requests, then inspect one request step by step."""
import json
import re
import time
from datetime import datetime, timezone

import requests

from ..config import JAEGER_URL

TRACE_ID_RE = re.compile(r"^[0-9a-fA-F]{16,32}$")

# Each service's main business endpoint. Searching by operation makes Jaeger filter
# server-side, so monitoring scrapes (GET /actuator/prometheus every 5s) never crowd out real requests.
DEFAULT_OPERATIONS = {
    "order-service": "POST /orders",
    "inventory-service": "POST /inventory/reserve",
    "payment-service": "POST /payments",
}


def _iso_us(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, tz=timezone.utc).isoformat(timespec="milliseconds")


def _tags(span: dict) -> dict:
    return {t["key"]: t.get("value") for t in span.get("tags", [])}


def _is_error(tags: dict) -> bool:
    return tags.get("error") in (True, "true") or tags.get("otel.status_code") == "ERROR"


def _summarize_trace(trace: dict):
    spans = trace.get("spans", [])
    if not spans:
        return None
    procs = trace.get("processes", {})

    def svc(span):
        return procs.get(span.get("processID"), {}).get("serviceName", "?")

    root = min(spans, key=lambda s: s["startTime"])
    start = min(s["startTime"] for s in spans)
    end = max(s["startTime"] + s["duration"] for s in spans)
    children = [s for s in spans if s is not root] or spans
    slowest = max(children, key=lambda s: s["duration"])
    errors = [s for s in spans if _is_error(_tags(s))]
    root_tags = _tags(root)
    return {
        "trace_id": trace["traceID"],
        "start": _iso_us(start),
        "duration_ms": round((end - start) / 1000, 2),
        "root": f"{svc(root)} {root['operationName']}",
        "http_status": root_tags.get("http.response.status_code") or root_tags.get("http.status_code"),
        "span_count": len(spans),
        "services": sorted({svc(s) for s in spans}),
        "has_error": bool(errors),
        "error_spans": [f"{svc(s)} {s['operationName']}" for s in errors][:5],
        "slowest_child_span": {
            "service": svc(slowest),
            "operation": slowest["operationName"],
            "duration_ms": round(slowest["duration"] / 1000, 2),
        },
    }


def find_traces(service: str, minutes: int = 15, min_duration_ms: int = None,
                errors_only: bool = False, limit: int = 10, operation: str = None) -> dict:
    """Finds recent request traces for a service, slowest first."""
    op = operation or DEFAULT_OPERATIONS.get(service)
    end_us = int(time.time() * 1e6)
    params = {
        "service": service,
        "start": end_us - minutes * 60 * 1_000_000,
        "end": end_us,
        "limit": max(limit * 5, 50),
    }
    if op:
        params["operation"] = op
    if min_duration_ms:
        params["minDuration"] = f"{int(min_duration_ms)}ms"
    if errors_only:
        params["tags"] = json.dumps({"error": "true"})
    resp = requests.get(f"{JAEGER_URL}/api/traces", params=params, timeout=20)
    resp.raise_for_status()
    traces = [t for t in (_summarize_trace(t) for t in resp.json().get("data") or []) if t]
    traces.sort(key=lambda t: t["duration_ms"], reverse=True)
    return {
        "service": service,
        "operation": op,
        "window_minutes": minutes,
        "filters": {"min_duration_ms": min_duration_ms, "errors_only": errors_only},
        "traces_found": len(traces),
        "traces": traces[:limit],
        "notes": ["http_status 409 on POST /orders means the order was rejected (e.g. unknown SKU): "
                  "a business outcome, not a system failure."],
    }


def get_trace(trace_id: str) -> dict:
    """Shows every step (span) of one request: which service, what operation, how long, any error."""
    if not TRACE_ID_RE.match(trace_id):
        raise ValueError("trace_id must be 16-32 hex characters")
    resp = requests.get(f"{JAEGER_URL}/api/traces/{trace_id}", timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    if not data:
        return {"trace_id": trace_id, "found": False}
    trace = data[0]
    procs = trace.get("processes", {})
    spans = sorted(trace.get("spans", []), key=lambda s: s["startTime"])
    t0 = spans[0]["startTime"] if spans else 0
    steps = []
    for s in spans[:60]:
        tags = _tags(s)
        step = {
            "service": procs.get(s.get("processID"), {}).get("serviceName", "?"),
            "operation": s["operationName"],
            "start_offset_ms": round((s["startTime"] - t0) / 1000, 2),
            "duration_ms": round(s["duration"] / 1000, 2),
            "error": _is_error(tags),
        }
        status = tags.get("http.response.status_code") or tags.get("http.status_code")
        if status is not None:
            step["http_status"] = status
        statement = tags.get("db.query.text") or tags.get("db.statement")
        if statement:
            step["db_statement"] = str(statement)[:200]
        for log in s.get("logs", []):
            fields = {f["key"]: f.get("value") for f in log.get("fields", [])}
            if "exception.type" in fields:
                step["exception"] = {
                    "type": fields.get("exception.type"),
                    "message": str(fields.get("exception.message"))[:300],
                }
                break
        steps.append(step)
    return {"trace_id": trace_id, "found": True, "span_count": len(spans), "steps": steps}
