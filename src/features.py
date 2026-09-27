"""Python does the math, Jev reads the result.

Everything here uses only bars that had *finished* before the decision time,
so the replay never peeks at the future.
"""

import html
from bisect import bisect_left
from datetime import timedelta

from market import to_et


class SymbolDay:
    """One symbol's 1-minute bars for one day, indexed by time."""

    def __init__(self, bars):
        bars = sorted(bars, key=lambda b: b["t"])
        self.times = [to_et(b["t"]) for b in bars]  # bar START times
        self.opens = [b["o"] for b in bars]
        self.highs = [b["h"] for b in bars]
        self.lows = [b["l"] for b in bars]
        self.closes = [b["c"] for b in bars]
        self.vols = [b["v"] for b in bars]
        self.vwaps = [b.get("vw", b["c"]) for b in bars]

    def _done(self, t):
        """Number of bars finished before time t (a bar starting at t-1min finishes at t)."""
        return bisect_left(self.times, t)

    def last_price(self, t):
        n = self._done(t)
        return self.closes[n - 1] if n else None

    def fill_price(self, t):
        """Price we'd actually trade at when deciding at t: the next bar's open."""
        n = self._done(t)
        if n < len(self.opens):
            return self.opens[n]
        return self.closes[-1] if self.closes else None

    def features(self, t):
        n = self._done(t)
        if n < 16:
            return None  # not enough history yet
        price = self.closes[n - 1]
        j = self._done(t - timedelta(minutes=15))
        ref15 = self.closes[j - 1] if j else self.opens[0]
        vol15 = sum(self.vols[j:n])
        minutes = max((t - self.times[0]).total_seconds() / 60, 15)
        pace15 = sum(self.vols[:n]) / minutes * 15
        vwap = sum(v * w for v, w in zip(self.vols[:n], self.vwaps[:n])) / max(sum(self.vols[:n]), 1)
        return {
            "price": price,
            "chg_day": price / self.opens[0] - 1,
            "chg15": price / ref15 - 1,
            "vol_ratio": vol15 / pace15 if pace15 else 1.0,
            "vs_vwap": price / vwap - 1,
            "from_high": price / max(self.highs[:n]) - 1,
            "from_low": price / min(self.lows[:n]) - 1,
            "rsi": rsi(self.closes[:n]),
        }


def rsi(closes, period=14):
    changes = [b - a for a, b in zip(closes[-period - 1:-1], closes[-period:])]
    gains = sum(c for c in changes if c > 0)
    losses = -sum(c for c in changes if c < 0)
    if losses == 0:
        return 100.0 if gains else 50.0
    return 100 - 100 / (1 + gains / losses)


def headlines(news, symbol, t, limit=3):
    """Most recent headlines about this symbol published today before t.
    Skips roundup articles tagged with many tickers ("10 tech stocks to watch")."""
    out = []
    for n in news:
        when = to_et(n["created_at"])
        if when < t and symbol in n["symbols"] and len(n["symbols"]) <= 3:
            mins = int((t - when).total_seconds() // 60)
            out.append((when, f"- ({mins} min ago) {html.unescape(n['headline'])[:150]}"))
    return [h for _, h in sorted(out, reverse=True)[:limit]]


def state_text(symbol, t, f, heads):
    """The plain-text 'state' Jev sees. Numbers are pre-computed and pre-rounded."""
    lines = [
        f"{symbol} at {t:%H:%M} ET | price {f['price']:.2f}",
        f"Today: {f['chg_day']:+.1%} since the open, {f['from_high']:+.1%} from today's high, "
        f"{f['from_low']:+.1%} from today's low",
        f"Last 15 min: {f['chg15']:+.2%}, volume {f['vol_ratio']:.1f}x today's average pace",
        f"Price vs VWAP: {f['vs_vwap']:+.2%} | RSI(14, 1-min): {f['rsi']:.0f}",
        "Headlines today:" + ("\n" + "\n".join(heads) if heads else " none"),
    ]
    return "\n".join(lines)
