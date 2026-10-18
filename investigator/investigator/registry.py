"""Tool registry: each tool's function, description, and parameter schema.

The schemas use JSON Schema, the same format LLM tool-calling APIs expect, so the agent (Day 4)
can be given these definitions directly.
"""
from .tools.deploys import get_commit_diff, get_recent_deployments
from .tools.logs import search_logs
from .tools.metrics import get_service_overview, query_metrics
from .tools.orders import get_order_outcomes
from .tools.traces import find_traces, get_trace

SERVICE_ENUM = ["order-service", "inventory-service", "payment-service"]

TOOLS = {
    "get_service_overview": {
        "fn": get_service_overview,
        "description": "Health overview of every service over the last N minutes: up/down, request rate, "
                       "5xx error rate, p95 latency, DB connection pool usage, and order-service's latency "
                       "to each dependency. Start every investigation here.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer", "description": "Look-back window in minutes", "default": 15},
        }},
    },
    "query_metrics": {
        "fn": query_metrics,
        "description": "Run any PromQL query over the last N minutes. Use for metrics the overview doesn't cover.",
        "parameters": {"type": "object", "required": ["promql"], "properties": {
            "promql": {"type": "string", "description": "A PromQL expression"},
            "minutes": {"type": "integer", "default": 15},
            "step_seconds": {"type": "integer", "default": 15},
        }},
    },
    "find_traces": {
        "fn": find_traces,
        "description": "Find recent request traces for a service, slowest first. Filter by minimum duration "
                       "or errors only. Each result names the slowest step inside the request.",
        "parameters": {"type": "object", "required": ["service"], "properties": {
            "service": {"type": "string", "enum": SERVICE_ENUM},
            "minutes": {"type": "integer", "default": 15},
            "min_duration_ms": {"type": "integer", "description": "Only traces at least this slow"},
            "errors_only": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 10},
        }},
    },
    "get_trace": {
        "fn": get_trace,
        "description": "Every step of one request: service, operation, timing, HTTP status, SQL statement, exceptions.",
        "parameters": {"type": "object", "required": ["trace_id"], "properties": {
            "trace_id": {"type": "string"},
        }},
    },
    "search_logs": {
        "fn": search_logs,
        "description": "Search a service's structured logs from the last N minutes. Similar lines are grouped "
                       "with counts. Filter by level (ERROR, WARN, INFO) and/or text.",
        "parameters": {"type": "object", "required": ["service"], "properties": {
            "service": {"type": "string", "enum": SERVICE_ENUM},
            "minutes": {"type": "integer", "default": 15},
            "level": {"type": "string", "enum": ["ERROR", "WARN", "INFO"]},
            "contains": {"type": "string", "description": "Case-insensitive text to match"},
            "max_groups": {"type": "integer", "default": 15},
        }},
    },
    "get_recent_deployments": {
        "fn": get_recent_deployments,
        "description": "Deployments in the last N minutes (service, git SHA, commit message, time). Compare "
                       "deploy times against when the problem started; a deploy after the problem began cannot be its cause.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer", "default": 180},
        }},
    },
    "get_commit_diff": {
        "fn": get_commit_diff,
        "description": "The files and code lines changed by a git commit.",
        "parameters": {"type": "object", "required": ["sha"], "properties": {
            "sha": {"type": "string", "description": "7-40 character git commit SHA"},
            "max_lines": {"type": "integer", "default": 200},
        }},
    },
    "get_order_outcomes": {
        "fn": get_order_outcomes,
        "description": "Customer impact: order statuses per minute (CONFIRMED, REJECTED, FAILED, "
                       "PAYMENT_UNKNOWN, PENDING) and current stock levels.",
        "parameters": {"type": "object", "properties": {
            "minutes": {"type": "integer", "default": 15},
        }},
    },
}


def call_tool(name: str, args: dict) -> dict:
    """Runs a tool by name. Errors are returned as data, so an agent can read them and adapt."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"Unknown tool '{name}'. Available: {sorted(TOOLS)}"}
    try:
        return tool["fn"](**(args or {}))
    except Exception as e:  # noqa: BLE001 - surfaced to the caller as data
        return {"error": f"{type(e).__name__}: {e}"}
