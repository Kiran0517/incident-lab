"""Log tools: search a service's structured JSON logs and group similar lines together.

Thousands of near-identical lines ("Order confirmed orderRef=<uuid>") are collapsed into one
group with a count, so an LLM sees the pattern instead of drowning in raw lines.
"""
import json
import re
import time

import docker

from ..config import COMPOSE_PROJECT

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def _template(message: str) -> str:
    return NUM_RE.sub("<n>", UUID_RE.sub("<uuid>", message))


def _container(service: str):
    client = docker.from_env()
    found = client.containers.list(all=True, filters={"label": [
        f"com.docker.compose.project={COMPOSE_PROJECT}",
        f"com.docker.compose.service={service}",
    ]})
    if not found:
        raise ValueError(f"No container found for service '{service}'")
    return found[0]


def search_logs(service: str, minutes: int = 15, level: str = None,
                contains: str = None, max_groups: int = 15) -> dict:
    """Searches a service's logs from the last N minutes, optionally filtered by level and text."""
    container = _container(service)
    raw = container.logs(since=int(time.time() - minutes * 60), stdout=True, stderr=True)
    groups = {}
    level_counts = {}
    non_json = 0
    matched = 0
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            non_json += 1
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            non_json += 1
            continue
        log_meta = entry.get("log") or {}
        lvl = log_meta.get("level", "?")
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
        if level and lvl.upper() != level.upper():
            continue
        message = entry.get("message", "")
        error = entry.get("error") or {}
        if contains:
            haystack = f"{message} {error.get('type', '')} {error.get('message', '')}".lower()
            if contains.lower() not in haystack:
                continue
        matched += 1
        logger = log_meta.get("logger", "")
        key = (lvl, logger, _template(message), error.get("type"))
        ts = entry.get("@timestamp")
        group = groups.get(key)
        if group is None:
            group = {
                "count": 0,
                "level": lvl,
                "logger": logger,
                "message_template": key[2][:300],
                "error_type": error.get("type"),
                "error_message": str(error.get("message"))[:300] if error.get("message") else None,
                "first_seen": ts,
                "last_seen": ts,
                "example_trace_id": entry.get("trace_id"),
            }
            groups[key] = group
        group["count"] += 1
        group["last_seen"] = ts

    ranked = sorted(groups.values(), key=lambda g: g["count"], reverse=True)[:max_groups]
    return {
        "service": service,
        "window_minutes": minutes,
        "filters": {"level": level, "contains": contains},
        "lines_by_level": level_counts,
        "matched_lines": matched,
        "non_json_lines_skipped": non_json,
        "groups": ranked,
    }
