"""Prometheus tools: raw PromQL queries and a pre-built health overview of every service."""
import math
import time
from datetime import datetime, timezone

import requests

from ..config import PROMETHEUS_URL, SERVICES


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _range(promql: str, minutes: int, step_seconds: int):
    """Runs a range query. Returns a list of (labels, [(timestamp, value), ...])."""
    end = time.time()
    start = end - minutes * 60
    resp = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": step_seconds},
        timeout=10,
    )
    body = resp.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus error: {body.get('error', resp.text[:200])}")
    series = []
    for s in body["data"]["result"]:
        points = []
        for ts, v in s["values"]:
            f = float(v)
            if not (math.isnan(f) or math.isinf(f)):
                points.append((float(ts), f))
        series.append((s["metric"], points))
    return series


def _summarize(points, max_samples: int = 8) -> dict:
    """Compresses a time series into a few numbers an LLM can reason about."""
    if not points:
        return {"no_data": True}
    values = [v for _, v in points]
    peak_ts, peak = max(points, key=lambda p: p[1])
    stride = max(1, math.ceil(len(points) / max_samples))
    return {
        "min": round(min(values), 3),
        "max": round(peak, 3),
        "avg": round(sum(values) / len(values), 3),
        "last": round(values[-1], 3),
        "peak_at": _iso(peak_ts),
        "samples": [] if min(values) == peak else [f"{_iso(t)[11:19]} {round(v, 2)}" for t, v in points[::stride]],
    }


def query_metrics(promql: str, minutes: int = 15, step_seconds: int = 15) -> dict:
    """Runs any PromQL query over the last N minutes and summarizes each series."""
    end = time.time()
    series = _range(promql, minutes, step_seconds)
    return {
        "query": promql,
        "window": {"start": _iso(end - minutes * 60), "end": _iso(end)},
        "series_count": len(series),
        "series": [{"labels": labels, **_summarize(points, 12)} for labels, points in series[:10]],
    }


def get_service_overview(minutes: int = 15) -> dict:
    """The first things an SRE checks: is each service up, how busy, how many errors, how slow,
    and is its database connection pool saturated. Plus how long order-service waits on each dependency."""
    step = max(15, (minutes * 60) // 60)
    end = time.time()
    services = {}
    for s in SERVICES:
        queries = {
            "up": f'min(up{{job="services", instance=~"{s}:.*"}})',
            "requests_per_sec": f'sum(rate(http_server_requests_seconds_count{{application="{s}", uri!~"/actuator.*"}}[1m])) or vector(0)',
            "errors_5xx_per_sec": f'sum(rate(http_server_requests_seconds_count{{application="{s}", uri!~"/actuator.*", status=~"5.."}}[1m])) or vector(0)',
            "p95_latency_ms": f'1000 * histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{{application="{s}", uri!~"/actuator.*"}}[1m])))',
            "db_pool_active": f'max(hikaricp_connections_active{{application="{s}"}})',
            "db_pool_pending": f'max(hikaricp_connections_pending{{application="{s}"}})',
            "db_pool_max": f'max(hikaricp_connections_max{{application="{s}"}})',
        }
        metrics = {}
        for name, promql in queries.items():
            result = _range(promql, minutes, step)
            metrics[name] = _summarize(result[0][1], 6) if result else {"no_data": True}
        services[s] = metrics

    deps = _range(
        '1000 * sum by (client_name) (rate(http_client_requests_seconds_sum{application="order-service"}[1m]))'
        ' / sum by (client_name) (rate(http_client_requests_seconds_count{application="order-service"}[1m]))',
        minutes,
        step,
    )
    dependency_latency = {labels.get("client_name", "unknown"): _summarize(points, 6) for labels, points in deps}

    return {
        "window": {"start": _iso(end - minutes * 60), "end": _iso(end)},
        "services": services,
        "order_service_dependency_avg_latency_ms": dependency_latency,
        "notes": [
            "up: 1 = Prometheus can scrape the service, 0 = unreachable.",
            "db_pool_active near db_pool_max with db_pool_pending > 0 means the DB connection pool is exhausted.",
            "In dependency latency, 'toxiproxy' is the network proxy in front of payment-service.",
            "no_data usually means no traffic of that kind in the window.",
        ],
    }
