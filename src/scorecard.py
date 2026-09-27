"""Daily paper-trading scorecard, built from Alpaca's order history (the source of truth).

Writes reports/paper-trading.md. GitHub Actions runs it after each close and commits the result.
"""

import os
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo

import broker
import config
import market

REPORT = os.path.join(os.path.dirname(__file__), "..", "reports", "paper-trading.md")
JEV_COST_PER_DAY = 0.0159  # measured in the replay: 10 tickers every 5 minutes


def spy_daily_changes(days):
    start = market._utc_window(days[0])[0]
    end = datetime.now(ZoneInfo("UTC"))
    bars = market._get(market.DATA_URL + "/v2/stocks/bars", {
        "symbols": config.BENCHMARK, "timeframe": "1Day", "start": market._iso(start),
        "end": market._iso(end), "feed": "iex", "adjustment": "all"})["bars"].get(config.BENCHMARK, [])
    return {market.to_et(b["t"]).date().isoformat(): b["c"] / b["o"] - 1 for b in bars}


def main():
    orders = [o for o in broker.bot_orders(config.LIVE_START + "T00:00:00Z")
              if o.get("filled_qty") and o.get("filled_avg_price")]
    by_day = defaultdict(list)
    for o in orders:
        by_day[market.to_et(o["filled_at"]).date().isoformat()].append(o)
    days = sorted(by_day)

    cash, lots, rows = config.STARTING_CASH, defaultdict(deque), []
    for d in days:
        wins = trips = 0
        pnl = 0.0
        for o in by_day[d]:
            qty, price = float(o["filled_qty"]), float(o["filled_avg_price"])
            if o["side"] == "buy":
                cash -= qty * price
                lots[o["symbol"]].append(price)
            else:
                cash += qty * price
                entry = lots[o["symbol"]].popleft() if lots[o["symbol"]] else price
                trips += 1
                wins += price > entry
                pnl += qty * (price - entry)
        open_syms = [s for s, q in lots.items() if q]
        rows.append((d, trips, wins, pnl, cash, open_syms))

    spy = spy_daily_changes(days) if days else {}
    lines = [
        "# Paper trading scorecard",
        "",
        f"Virtual ${config.STARTING_CASH:.2f} account since {config.LIVE_START}. "
        f"Jev thresholds: buy >= {config.LIVE_BUY_THRESHOLD}, sell >= {config.LIVE_SELL_THRESHOLD}. "
        f"Jev cost is the replay-measured ${JEV_COST_PER_DAY}/day.",
        "",
        "| Day | Round trips | Wins | Realized P/L | Cash at close | Bot total | SPY that day | SPY total | Held overnight |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    spy_total = 1.0
    for d, trips, wins, pnl, cash_d, open_syms in rows:
        spy_total *= 1 + spy.get(d, 0)
        lines.append(
            f"| {d} | {trips} | {wins} | ${pnl:+.4f} | ${cash_d:.4f} | "
            f"{cash_d / config.STARTING_CASH - 1:+.2%} | {spy.get(d, 0):+.2%} | {spy_total - 1:+.2%} | "
            f"{', '.join(open_syms) or '-'} |")
    if rows:
        n = len(rows)
        net = rows[-1][4] - config.STARTING_CASH - JEV_COST_PER_DAY * n
        lines += ["", f"**After {n} trading day(s):** bot {rows[-1][4] / config.STARTING_CASH - 1:+.2%} "
                      f"before Jev cost, net ${net:+.4f} after ~${JEV_COST_PER_DAY * n:.3f} of Jev; "
                      f"SPY {spy_total - 1:+.2%}."]
    else:
        lines += ["", "No trades yet."]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
