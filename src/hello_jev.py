"""Phase 0: make one Jev call through OpenRouter and look at what comes back.

Run:  python3 src/hello_jev.py

Needs OPENROUTER_API_KEY, either as an environment variable or in a .env file
in the project folder. Uses only the Python standard library.
"""

import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"


def load_key():
    """Read the key from the environment, falling back to a .env file."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            name, _, value = line.strip().partition("=")
            if name == "OPENROUTER_API_KEY" and value:
                return value
    raise SystemExit("OPENROUTER_API_KEY not found (env var or .env file)")


def decide(state, questions):
    """Send one state + typed questions to Jev. Returns (response, milliseconds)."""
    body = json.dumps({"model": MODEL, "state": state, "questions": questions})
    req = urllib.request.Request(
        API_URL,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {load_key()}",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as err:
        raise SystemExit(f"HTTP {err.code}: {err.read().decode()}")
    check_typesafe(data, questions)
    return data, (time.perf_counter() - start) * 1000


def check_typesafe(resp, questions):
    """Refuse the answer unless TypeSafe served it and every answer has the type we asked for."""
    provider = str(resp.get("provider", ""))
    if "typesafe" not in provider.lower():
        raise SystemExit(f"Not served by TypeSafe (provider={provider!r}); refusing to use it")
    for name, q in questions.items():
        answer = resp.get("answers", {}).get(name)
        if answer is None or answer.get("type") != q["type"]:
            raise SystemExit(f"Answer {name!r} missing or wrong type: {answer!r}")


# The same three questions asked about every held position.
HOLDING_QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": "Should a short-term day trader keep or exit this position right now?",
        "criteria": {
            "HOLD": "Trend intact, no clear reason to exit",
            "SELL": "Momentum fading, risk rising, or a gain worth locking in",
        },
    },
    "momentum": {
        "type": "score",
        "instructions": "How strong is this stock's short-term momentum?",
        "criteria": ["fading", "flat", "strong"],
    },
    "bad_news": {
        "type": "noul",
        "instructions": "Do the headlines contain news likely to push this stock down today?",
    },
}

# Hand-written test situations: one obvious SELL, one obvious HOLD, one unclear.
# Python would compute these numbers in the real bot; Jev only judges them.
TEST_STATES = {
    "collapsing": (
        "XYZ | held: bought at 50.00, now 48.60 (-2.8%)\n"
        "Last 15 min: -1.9%, volume 4x normal, price 1.5% below VWAP, RSI 28\n"
        "Headlines (last hour): 'XYZ cuts full-year guidance, CFO resigns'"
    ),
    "strong": (
        "ABC | held: bought at 120.00, now 122.10 (+1.8%)\n"
        "Last 15 min: +0.9%, volume 2x normal, price 0.8% above VWAP, RSI 61\n"
        "Headlines (last hour): 'ABC wins large government contract'"
    ),
    "boring": (
        "QRS | held: bought at 33.00, now 33.02 (+0.1%)\n"
        "Last 15 min: 0.0%, volume 0.7x normal, price at VWAP, RSI 50\n"
        "Headlines (last hour): none"
    ),
}


def main():
    total_cost = 0.0
    for name, state in TEST_STATES.items():
        resp, ms = decide(state, HOLDING_QUESTIONS)
        if name == "collapsing":
            # First call: print everything so we can confirm the real field names.
            print("=== RAW RESPONSE (first call) ===")
            print(json.dumps(resp, indent=2))
        a = resp["answers"]
        cost = resp.get("usage", {}).get("cost", 0) or 0
        total_cost += cost
        print(f"\n--- {name} ({ms:.0f} ms, ${cost:.6f}, served by {resp.get('provider')} / {resp.get('model')}) ---")
        print(f"  action:   {a['action']['choice']}  (confidence {a['action'].get('confidence', 0):.2f})")
        print(f"  momentum: {a['momentum']['score']}  (0=fading, 1=flat, 2=strong)")
        print(f"  bad_news: P(yes) = {a['bad_news']['noul']:.2f}")
    print(f"\nTotal cost for {len(TEST_STATES)} calls: ${total_cost:.6f}")


if __name__ == "__main__":
    main()
