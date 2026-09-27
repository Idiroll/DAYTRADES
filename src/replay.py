"""Phase 1: replay past trading days through the bot with a simulated $10 account.

Run:  python3 src/replay.py --start 2026-09-18 --end 2026-09-25

1. Downloads 1-minute bars + headlines from Alpaca (cached in data/).
2. Builds the text state for every ticker at every 5-minute cycle.
3. Asks Jev about every state once (cached; answers are reused for every threshold).
4. Simulates each strategy minute by minute with the hard risk rules.
5. Tunes on the first half of the days, reports how the chosen setting does on the second half.
"""

import argparse
import concurrent.futures as cf
from datetime import datetime, timedelta

import config
import jev
import market
from features import SymbolDay, headlines, state_text
from strategies import QUESTIONS, jev_strategy, rules_strategy


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=market.ET)


def cycle_times(day):
    t, end = at(day, config.FIRST_CYCLE), at(day, config.LAST_ENTRY)
    while t <= end:
        yield t
        t += timedelta(minutes=config.CYCLE_MINUTES)


def load_day(day):
    bars = market.bars_for_day(day, config.WATCHLIST)
    news = market.news_for_day(day, config.WATCHLIST)
    syms = {s: SymbolDay(b) for s, b in bars.items() if b}
    snapshots = {}  # (symbol, time) -> (features, state text)
    for t in cycle_times(day):
        for s, sd in syms.items():
            f = sd.features(t)
            if f:
                snapshots[(s, t)] = (f, state_text(s, t, f, headlines(news, s, t)))
    return syms, snapshots


def ask_jev(all_snapshots):
    """Get a Jev answer for every state, calling the API only for ones not in the cache."""
    cache = jev.load_cache()
    keyed = {jev._key(state, QUESTIONS): state for _, state in all_snapshots.values()}
    todo = {k: s for k, s in keyed.items() if k not in cache}
    est = len(todo) * 0.00002
    print(f"Jev: {len(keyed)} states, {len(keyed) - len(todo)} cached, {len(todo)} to ask (~${est:.4f})")
    if est > config.MAX_JEV_COST:
        raise SystemExit(f"Estimated cost ${est:.2f} exceeds MAX_JEV_COST ${config.MAX_JEV_COST}")
    spent, done = 0.0, 0
    with cf.ThreadPoolExecutor(config.JEV_WORKERS) as pool:
        futures = {pool.submit(jev.decide, s, QUESTIONS): k for k, s in todo.items()}
        for fut in cf.as_completed(futures):
            k = futures[fut]
            resp = fut.result()
            jev.save_to_cache(k, resp)
            cache[k] = resp
            spent += resp.get("usage", {}).get("cost", 0) or 0
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(todo)} answered, ${spent:.4f} so far")
    total_cost = sum((cache[k].get("usage", {}).get("cost", 0) or 0) for k in keyed)
    answers = {key: cache[jev._key(state, QUESTIONS)]["answers"] for key, (_, state) in all_snapshots.items()}
    return answers, spent, total_cost


def simulate_day(day, syms, snapshots, answers, strategy):
    """Minute-by-minute simulation of one day. Returns (end_equity_ratio, trades)."""
    cash = 1.0  # work in fractions of starting equity, scale by $10 when reporting
    positions = {}  # symbol -> (shares, entry_price)
    last_sold = {}
    trades = []

    def sell(s, t, price, why):
        nonlocal cash
        shares, entry = positions.pop(s)
        fill = price * (1 - config.SLIPPAGE)
        cash += shares * fill
        trades.append({"symbol": s, "entry": entry, "exit": fill, "ret": fill / entry - 1, "why": why})
        last_sold[s] = t

    t, close = at(day, "09:31"), at(day, config.FLATTEN_AT)
    cycles = set(cycle_times(day))
    while t <= close:
        # Hard rules every minute: stop-loss, take-profit, flatten at the end of the day.
        for s in list(positions):
            price = syms[s].last_price(t)
            ret = price / positions[s][1] - 1
            if t >= close:
                sell(s, t, syms[s].fill_price(t), "end of day")
            elif ret <= config.STOP_LOSS:
                sell(s, t, price, "stop-loss")
            elif ret >= config.TAKE_PROFIT:
                sell(s, t, price, "take-profit")

        if t in cycles:
            sigs = {}
            for s in syms:
                if (s, t) in snapshots:
                    f, _ = snapshots[(s, t)]
                    sigs[s] = strategy(f, answers.get((s, t)))
            for s in list(positions):
                if s in sigs and sigs[s].sell:
                    sell(s, t, syms[s].fill_price(t), "signal")
            buys = sorted(
                (s for s, g in sigs.items()
                 if g.buy and s not in positions
                 and t - last_sold.get(s, t - timedelta(days=1)) >= timedelta(minutes=config.COOLDOWN_MINUTES)),
                key=lambda s: -sigs[s].rank,
            )
            for s in buys:
                slots = config.MAX_POSITIONS - len(positions)
                if slots <= 0 or cash <= 0.01:
                    break
                spend = cash / slots
                fill = syms[s].fill_price(t) * (1 + config.SLIPPAGE)
                positions[s] = (spend / fill, fill)
                cash -= spend
        t += timedelta(minutes=1)
    return cash, trades


def benchmark_day(syms):
    sd = syms[config.BENCHMARK]
    return sd.closes[-1] / sd.opens[0]


def run_period(days, data, answers, strategy):
    equity, trades = 1.0, []
    daily = []
    for d in days:
        syms, snaps = data[d]
        ratio, tr = simulate_day(d, syms, snaps, answers, strategy)
        equity *= ratio
        daily.append(equity)
        trades += tr
    peak, dd = 1.0, 0.0
    for e in daily:
        peak = max(peak, e)
        dd = min(dd, e / peak - 1)
    wins = [t for t in trades if t["ret"] > 0]
    return {"ret": equity - 1, "trades": len(trades), "win": len(wins) / len(trades) if trades else 0,
            "dd": dd, "per_day": len(trades) / len(days)}


def fmt(name, r, jev_cost=0.0):
    dollars = config.STARTING_CASH * r["ret"] - jev_cost
    return (f"  {name:<28} {r['ret']:+7.2%}  {r['trades']:>4} trades ({r['per_day']:.1f}/day)  "
            f"win {r['win']:.0%}  maxDD {r['dd']:+.2%}  net on $10 after Jev: ${dollars:+.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-18", help="first day (after Jev's 2026-09-17 model date)")
    ap.add_argument("--end", default="2026-09-25")
    args = ap.parse_args()

    days = market.trading_days(args.start, args.end)
    if len(days) < 2:
        raise SystemExit("Need at least 2 trading days to tune and test")
    half = len(days) // 2
    tune, test = days[:half], days[half:]
    print(f"Tune days: {tune}\nTest days: {test}")

    data, all_snaps = {}, {}
    for d in days:
        data[d] = load_day(d)
        all_snaps.update(data[d][1])
    answers, spent, total_cost = ask_jev(all_snaps)
    print(f"Jev spent this run: ${spent:.4f} | total Jev cost of all answers used: ${total_cost:.4f}")
    cost_per_day = total_cost / len(days)

    jev_strats = [jev_strategy(b, s) for b in config.BUY_THRESHOLDS for s in config.SELL_THRESHOLDS]
    rules = rules_strategy()

    def bench(ds):
        e = 1.0
        for d in ds:
            e *= benchmark_day(data[d][0])
        return e - 1

    print(f"\n=== TUNE period ({len(tune)} days) — SPY buy & hold: {bench(tune):+.2%} ===")
    results = []
    for st in jev_strats:
        r = run_period(tune, data, answers, st)
        results.append((r["ret"], st, r))
        print(fmt(st.name, r, cost_per_day * len(tune)))
    print(fmt(rules.name, run_period(tune, data, answers, rules)))

    best = max(results, key=lambda x: x[0])[1]
    print(f"\nBest Jev setting on tune days: {best.name}")

    print(f"\n=== TEST period ({len(test)} days, unseen) — SPY buy & hold: {bench(test):+.2%} ===")
    print(fmt(best.name + " (chosen)", run_period(test, data, answers, best), cost_per_day * len(test)))
    print(fmt(rules.name, run_period(test, data, answers, rules)))
    print(f"\nJev cost per day for {len(config.WATCHLIST)} tickers every {config.CYCLE_MINUTES} min: "
          f"${cost_per_day:.4f} ({cost_per_day / config.STARTING_CASH:.2%} of a $10 account)")


if __name__ == "__main__":
    main()
