"""Experiment 2: can Jev read headlines well enough to predict the move that follows?

For every in-session headline about one watchlist stock, Jev rates its likely price
impact and whether it is genuinely new, material information. We then measure what
the stock did over the next 30/60/120 minutes, minus SPY's move over the same window
(for SPY headlines: SPY's own move). If Jev can read news, "positive" headlines should
be followed by gains and "negative" ones by losses.

Run:  python3 src/news_study.py --start 2026-06-18 --end 2026-09-25
"""

import argparse
import concurrent.futures as cf
import html
import math
from collections import defaultdict
from datetime import datetime, timedelta

import config
import jev
import market
from features import SymbolDay

QUESTIONS = {
    "impact": {
        "type": "score",
        "instructions": "What is this headline's likely impact on the named stock's price over the next hour?",
        "criteria": ["strongly negative", "somewhat negative", "neutral", "somewhat positive", "strongly positive"],
    },
    "material": {
        "type": "noul",
        "instructions": "Is this headline genuinely new, material information about the named stock "
                        "(not a recap, listicle, opinion piece, or routine data point)?",
    },
}
HORIZONS = [30, 60, 120]
ROUND_TRIP_COST = 2 * config.SLIPPAGE


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=market.ET)


def collect(days):
    """One event per (headline, watchlist symbol) published 09:30-15:00 ET."""
    events = []
    for d in days:
        news = market.news_for_day(d, config.WATCHLIST)
        syms = {s: SymbolDay(b) for s, b in market.bars_for_day(d, config.WATCHLIST).items() if b}
        spy = syms[config.BENCHMARK]
        close = at(d, "15:59")
        for n in news:
            t = market.to_et(n["created_at"])
            if not (at(d, "09:30") <= t < at(d, "15:00")) or len(n["symbols"]) > 3:
                continue
            entry_t = t.replace(second=0, microsecond=0) + timedelta(minutes=1)
            for s in n["symbols"]:
                if s not in syms:
                    continue
                sd = syms[s]
                p0, m0 = sd.fill_price(entry_t), spy.fill_price(entry_t)
                pre = sd.last_price(entry_t)
                pre15 = sd.last_price(entry_t - timedelta(minutes=15))
                fwd = {}
                for h in HORIZONS:
                    t1 = min(entry_t + timedelta(minutes=h), close)
                    r = sd.last_price(t1) / p0 - 1
                    fwd[h] = r if s == config.BENCHMARK else r - (spy.last_price(t1) / m0 - 1)
                state = (f"Stock: {s}\nPublished: {t:%H:%M} ET\n"
                         f"Headline: {html.unescape(n['headline'])[:200]}")
                events.append({"day": d, "symbol": s, "state": state, "fwd": fwd,
                               "pre15": (pre / pre15 - 1) if pre and pre15 else 0.0})
    return events


def ask(events):
    cache = jev.load_cache()
    todo = {jev._key(e["state"], QUESTIONS): e["state"] for e in events}
    todo = {k: s for k, s in todo.items() if k not in cache}
    print(f"Jev: {len(events)} events, {len(todo)} new calls (~${len(todo) * 0.00002:.4f})")
    failed = 0
    with cf.ThreadPoolExecutor(config.JEV_WORKERS) as pool:
        futures = {pool.submit(jev.decide, s, QUESTIONS): k for k, s in todo.items()}
        for fut in cf.as_completed(futures):
            try:
                resp = fut.result()
            except Exception as err:
                failed += 1
                print(f"  failed: {str(err)[:150]}")
                continue
            jev.save_to_cache(futures[fut], resp)
            cache[futures[fut]] = resp
    for e in events:
        resp = cache.get(jev._key(e["state"], QUESTIONS))
        e["ans"] = resp["answers"] if resp else None
    cost = sum(cache[jev._key(e["state"], QUESTIONS)].get("usage", {}).get("cost", 0) or 0
               for e in events if e["ans"])
    return [e for e in events if e["ans"]], cost, failed


def stats(values):
    n = len(values)
    if n < 2:
        return n, (values[0] if values else 0), 0.0
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    return n, mean, mean / (sd / math.sqrt(n)) if sd else 0.0


def table(title, groups, h):
    print(f"\n{title} (next {h} min, vs SPY)")
    for name, evs in groups:
        n, mean, t = stats([e["fwd"][h] for e in evs])
        flag = "  <- |t|>2" if abs(t) > 2 and n >= 20 else ""
        print(f"  {name:<34} n={n:<5} avg {mean:+.3%}  t={t:+.1f}{flag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-18")
    ap.add_argument("--end", default="2026-09-25")
    args = ap.parse_args()
    days = market.trading_days(args.start, args.end)
    events, cost, failed = ask(collect(days))
    print(f"{len(events)} events answered, Jev cost ${cost:.4f}, {failed} failed")

    labels = QUESTIONS["impact"]["criteria"]
    for e in events:
        e["bucket"] = labels[min(int(round(e["ans"]["impact"]["score"])), 4)]
        e["material"] = e["ans"]["material"]["noul"] >= 0.5

    material = [e for e in events if e["material"]]
    print(f"Material (P>=0.5): {len(material)} of {len(events)}")
    for h in HORIZONS:
        table("ALL headlines by Jev impact", [(b, [e for e in events if e["bucket"] == b]) for b in labels], h)
        table("MATERIAL headlines by Jev impact",
              [(b, [e for e in material if e["bucket"] == b]) for b in labels], h)

    # Out-of-sample check and a simple trading rule, both on material headlines.
    half = days[len(days) // 2]
    for name, sel in [("first half", lambda e: e["day"] < half), ("second half", lambda e: e["day"] >= half)]:
        pos = [e for e in material if sel(e) and e["bucket"] in labels[3:]]
        neg = [e for e in material if sel(e) and e["bucket"] in labels[:2]]
        table(f"{name}: positive vs negative material", [("positive", pos), ("negative", neg)], 60)

    trades = [e["fwd"][60] - ROUND_TRIP_COST for e in material if e["bucket"] in labels[3:]]
    n, mean, t = stats(trades)
    print(f"\nRule 'buy on material positive headline, sell 60 min later', after costs: "
          f"{n} trades, avg {mean:+.3%} per trade, t={t:+.1f}")

    pre_pos = [e["pre15"] for e in material if e["bucket"] in labels[3:]]
    if pre_pos:
        print(f"Move in the 15 min BEFORE positive material headlines: avg {sum(pre_pos) / len(pre_pos):+.3%} "
              f"(big = news already priced in by the time it's published)")


if __name__ == "__main__":
    main()
