"""Alpaca paper-trading orders, plus a virtual $10 account on top of the $100k paper balance.

The paper account starts with $100,000, but the experiment is about $10. So the bot
keeps its own books: every order it places is tagged with a client_order_id starting
with ORDER_TAG, and its "cash" is $10 minus what it spent on buys plus what it got
from sells. Nothing needs saving between runs; the order history is the ledger.
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

import config

PAPER_URL = "https://paper-api.alpaca.markets"
ORDER_TAG = "jev-"


def _call(method, path, body=None):
    req = urllib.request.Request(
        PAPER_URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"Alpaca {method} {path}: HTTP {err.code} {err.read().decode()[:300]}")


def clock():
    return _call("GET", "/v2/clock")


def positions():
    """{symbol: {qty, avg_entry_price, current_price, unrealized_plpc, market_value}} as floats."""
    out = {}
    for p in _call("GET", "/v2/positions"):
        out[p["symbol"]] = {k: float(p[k]) for k in
                            ("qty", "avg_entry_price", "current_price", "unrealized_plpc", "market_value")}
    return out


def bot_orders(after_iso):
    """All orders this bot placed since after_iso (oldest first), across pages."""
    out, after = [], after_iso
    while True:
        page = _call("GET", f"/v2/orders?status=all&direction=asc&limit=500&after={after}")
        page = [o for o in page if o["submitted_at"] > after]
        if not page:
            return [o for o in out if (o.get("client_order_id") or "").startswith(ORDER_TAG)]
        out += page
        after = page[-1]["submitted_at"]


def virtual_cash(orders):
    """$10 minus money spent on filled buys plus money received from filled sells."""
    cash = config.STARTING_CASH
    for o in orders:
        if o.get("filled_qty") and o.get("filled_avg_price"):
            value = float(o["filled_qty"]) * float(o["filled_avg_price"])
            cash += value if o["side"] == "sell" else -value
    return cash


def buy(symbol, dollars):
    return _call("POST", "/v2/orders", {
        "symbol": symbol, "notional": f"{dollars:.2f}", "side": "buy", "type": "market",
        "time_in_force": "day", "client_order_id": f"{ORDER_TAG}{uuid.uuid4().hex[:20]}",
    })


def sell_all(symbol, qty):
    return _call("POST", "/v2/orders", {
        "symbol": symbol, "qty": f"{qty:.9f}".rstrip("0").rstrip("."), "side": "sell", "type": "market",
        "time_in_force": "day", "client_order_id": f"{ORDER_TAG}{uuid.uuid4().hex[:20]}",
    })


def wait_filled(order, seconds=20):
    """Poll until the order is filled (market orders usually fill in about a second)."""
    for _ in range(seconds):
        o = _call("GET", f"/v2/orders/{order['id']}")
        if o["status"] in ("filled", "canceled", "rejected", "expired"):
            return o
        time.sleep(1)
    return o
