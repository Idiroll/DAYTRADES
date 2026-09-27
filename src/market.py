"""Alpaca market data: trading calendar, 1-minute bars, news. Cached to data/ per day."""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


def _get(url, params):
    req = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params),
        headers={
            "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _cached(name, fetch):
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    data = fetch()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def trading_days(start, end):
    """Regular full trading days between two YYYY-MM-DD dates (inclusive)."""
    cal = _get(PAPER_URL + "/v2/calendar", {"start": start, "end": end})
    return [d["date"] for d in cal if d["open"] == "09:30" and d["close"] == "16:00"]


def _utc_window(day):
    open_ = datetime.fromisoformat(f"{day}T09:30").replace(tzinfo=ET)
    close = datetime.fromisoformat(f"{day}T16:00").replace(tzinfo=ET)
    return open_.astimezone(ZoneInfo("UTC")), close.astimezone(ZoneInfo("UTC"))


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def bars_for_day(day, symbols):
    """{symbol: [{t, o, h, l, c, v, vw}, ...]} for regular hours. IEX feed (free)."""

    def fetch():
        start, end = _utc_window(day)
        out, token = {}, None
        while True:
            params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": _iso(start),
                      "end": _iso(end), "feed": "iex", "limit": 10000, "adjustment": "raw"}
            if token:
                params["page_token"] = token
            page = _get(DATA_URL + "/v2/stocks/bars", params)
            for sym, bars in (page.get("bars") or {}).items():
                out.setdefault(sym, []).extend(bars)
            token = page.get("next_page_token")
            if not token:
                return out

    return _cached(f"bars_{day}.json", fetch)


def news_for_day(day, symbols):
    """Headlines from 04:00 ET (pre-market) to the close: [{created_at, headline, symbols}]."""

    def fetch():
        _, end = _utc_window(day)
        start = datetime.fromisoformat(f"{day}T04:00").replace(tzinfo=ET).astimezone(ZoneInfo("UTC"))
        out, token = [], None
        while True:
            params = {"symbols": ",".join(symbols), "start": _iso(start), "end": _iso(end),
                      "limit": 50, "sort": "asc"}
            if token:
                params["page_token"] = token
            page = _get(DATA_URL + "/v1beta1/news", params)
            out += [{"created_at": n["created_at"], "headline": n["headline"], "symbols": n["symbols"]}
                    for n in page.get("news", [])]
            token = page.get("next_page_token")
            if not token:
                return out

    return _cached(f"news_{day}.json", fetch)


def to_et(ts):
    """Alpaca UTC timestamp string -> aware datetime in US Eastern."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET)
