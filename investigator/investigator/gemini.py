"""Minimal Gemini API client (REST) with function calling and rate-limit retries.

Uses plain HTTP instead of an SDK so every request and response is easy to inspect.
"""
import os
import sys
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    pass


class QuotaExhausted(GeminiError):
    """The daily free-tier quota for this model is used up; retrying today is pointless."""


def _quota_info(resp) -> dict:
    """Reads Google's structured 429 error: which quota was hit, its limit, and when to retry."""
    info = {"daily": False, "limit": None, "retry_seconds": None, "message": resp.text[:300]}
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return info
    info["message"] = err.get("message", "")[:300]
    for detail in err.get("details", []):
        kind = detail.get("@type", "")
        if kind.endswith("QuotaFailure"):
            for v in detail.get("violations", []):
                if "PerDay" in v.get("quotaId", ""):
                    info["daily"] = True
                info["limit"] = v.get("quotaValue", info["limit"])
        elif kind.endswith("RetryInfo"):
            delay = detail.get("retryDelay", "")
            if delay.endswith("s"):
                try:
                    info["retry_seconds"] = float(delay[:-1])
                except ValueError:
                    pass
    return info


def _human(seconds: float) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m" if seconds >= 3600 else f"{seconds // 60}m {seconds % 60}s"


def clean_schema(schema):
    """Gemini accepts a subset of JSON Schema; drop keys it rejects (like 'default')."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k != "default"}
    if isinstance(schema, list):
        return [clean_schema(x) for x in schema]
    return schema


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout: int = 180):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # Free tiers allow only a few requests per minute; spacing calls avoids most 429 errors.
        self.min_interval = float(os.getenv("GEMINI_MIN_INTERVAL_SECONDS", "6"))
        self._last_call = 0.0

    def _pace(self):
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def generate(self, system: str, contents: list, tools: list = None, allow_tools: bool = True) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.1},
        }
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
            if not allow_tools:
                body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
        for attempt in range(4):
            self._pace()
            resp = requests.post(
                f"{API}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
            if resp.status_code == 429:
                info = _quota_info(resp)
                if info["daily"]:
                    raise QuotaExhausted(
                        f"Daily free-tier quota used up for {self.model} (limit {info['limit']} requests/day). "
                        f"Resets in about {_human(info['retry_seconds'])}. "
                        f"Set a different GEMINI_MODEL in .env, or wait.")
                wait = min(info["retry_seconds"] or 20 * (attempt + 1), 90)
                print(f"  (rate limited: {info['message'][:120]}... waiting {int(wait)}s)",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 20 * (attempt + 1)
                print(f"  (model API returned {resp.status_code}; waiting {wait}s and retrying)",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                raise GeminiError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            return resp.json()
        raise GeminiError("Gave up after repeated rate-limit or server errors")


def list_models(api_key: str) -> list:
    """Models available to this API key that support generateContent."""
    resp = requests.get(f"{API}/models", params={"pageSize": 200},
                        headers={"x-goog-api-key": api_key}, timeout=30)
    if resp.status_code != 200:
        raise GeminiError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    names = []
    for m in resp.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(m["name"].removeprefix("models/"))
    return sorted(names)
