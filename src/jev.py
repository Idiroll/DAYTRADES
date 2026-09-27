"""Jev client: OpenRouter Decisions API, TypeSafe-only, with an answer cache.

The cache matters for experiments: an answer depends only on (state, questions),
so re-running a replay with different thresholds costs nothing extra.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

import config

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "jev_cache.jsonl")


def _key(state, questions):
    raw = json.dumps([config.JEV_MODEL, state, questions], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def load_cache():
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            for line in f:
                row = json.loads(line)
                cache[row["key"]] = row["resp"]
    return cache


def save_to_cache(key, resp):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "a") as f:
        f.write(json.dumps({"key": key, "resp": resp}) + "\n")


def check_typesafe(resp, questions):
    """Refuse the answer unless TypeSafe served it and every answer has the type we asked for."""
    provider = str(resp.get("provider", ""))
    if "typesafe" not in provider.lower():
        raise RuntimeError(f"Not served by TypeSafe (provider={provider!r})")
    for name, q in questions.items():
        answer = resp.get("answers", {}).get(name)
        if answer is None or answer.get("type") != q["type"]:
            raise RuntimeError(f"Answer {name!r} missing or wrong type: {answer!r}")


def decide(state, questions, retries=4):
    """One live Jev call. Retries on rate limits and server errors."""
    body = json.dumps({"model": config.JEV_MODEL, "state": state, "questions": questions})
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            config.JEV_URL,
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
            check_typesafe(resp, questions)
            return resp
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {err.code}: {err.read().decode()[:300]}")
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise
