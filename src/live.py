"""Phase 2: one live paper-trading cycle. GitHub Actions runs this every 5 minutes.

Each run is independent: it reads positions and order history from Alpaca, asks Jev
about every watchlist ticker, applies the same glue and hard rules as the replay,
places paper orders, and writes what it did to logs/YYYY-MM-DD.jsonl.

  python3 src/live.py                                  # real run (does nothing if the market is closed)
  python3 src/live.py --dry-run --at 2026-09-25T11:00  # test on a past moment; no orders placed
"""

import argparse
import concurrent.futures as cf
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import broker
import config
import jev
import market
from features import SymbolDay, headlines, state_text
from strategies import QUESTIONS, jev_strategy

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=market.ET)


def run(now, dry_run):
    day = now.date().isoformat()
    log = []

    def record(**entry):
        entry["time"] = now.isoformat()
        log.append(entry)
        print(json.dumps({k: v for k, v in entry.items() if k != "state"}))

    orders = broker.bot_orders(config.LIVE_START + "T00:00:00Z")
    cash = broker.virtual_cash(orders)
    held = {s: p for s, p in broker.positions().items() if s in config.WATCHLIST}
    record(event="start", virtual_cash=round(cash, 4), held=list(held), dry_run=dry_run)

    def sell(symbol, why):
        nonlocal cash
        if dry_run:
            record(event="sell", symbol=symbol, why=why, dry_run=True)
        else:
            o = broker.wait_filled(broker.sell_all(symbol, held[symbol]["qty"]))
            if o.get("filled_avg_price"):
                cash += float(o["filled_qty"]) * float(o["filled_avg_price"])
            record(event="sell", symbol=symbol, why=why, status=o["status"],
                   price=o.get("filled_avg_price"), qty=o.get("filled_qty"))
        held.pop(symbol)

    # 1. Hard rules first, whatever Jev would say.
    for s in list(held):
        ret = held[s]["unrealized_plpc"]
        if now >= at(day, config.LIVE_FLATTEN_AT):
            sell(s, "end of day")
        elif ret <= config.STOP_LOSS:
            sell(s, f"stop-loss {ret:+.2%}")
        elif ret >= config.TAKE_PROFIT:
            sell(s, f"take-profit {ret:+.2%}")

    if not (at(day, config.FIRST_CYCLE) <= now <= at(day, config.LAST_ENTRY)):
        record(event="end", note="outside decision window", virtual_cash=round(cash, 4))
        return log

    # 2. Python does the math: today's bars and headlines -> plain-text state per ticker.
    utc_now = now.astimezone(ZoneInfo("UTC"))
    open_utc, _ = market._utc_window(day)
    bars = market.fetch_bars(config.WATCHLIST, open_utc, utc_now)
    news = market.fetch_news(config.WATCHLIST, market.premarket_start(day), utc_now)
    snaps = {}
    for s in config.WATCHLIST:
        f = SymbolDay(bars.get(s, [])).features(now) if bars.get(s) else None
        if f:
            snaps[s] = (f, state_text(s, now, f, headlines(news, s, now)))

    # 3. Jev judges every ticker (one call each, in parallel).
    with cf.ThreadPoolExecutor(config.JEV_WORKERS) as pool:
        futures = {s: pool.submit(jev.decide, state, QUESTIONS) for s, (_, state) in snaps.items()}
    answers, jev_cost = {}, 0.0
    for s, fut in futures.items():
        try:
            resp = fut.result()
        except Exception as err:
            record(event="jev_error", symbol=s, error=str(err)[:200])
            continue
        answers[s] = resp["answers"]
        jev_cost += resp.get("usage", {}).get("cost", 0) or 0

    # 4. Dumb glue: answers -> signals, then sells, then buys.
    strategy = jev_strategy(config.LIVE_BUY_THRESHOLD, config.LIVE_SELL_THRESHOLD)
    sigs = {s: strategy(snaps[s][0], a) for s, a in answers.items()}
    for s, a in answers.items():
        probs = a["momentum"]["probabilities"]
        record(event="decision", symbol=s, buy=sigs[s].buy, sell=sigs[s].sell,
               p_strong=probs.get("2"), p_fading=probs.get("0"), bad_news=a["bad_news"]["noul"],
               good_news=a["good_news"]["noul"], overextended=a["overextended"]["noul"],
               state=snaps[s][1])
    for s in list(held):
        if s in sigs and sigs[s].sell:
            sell(s, "jev signal")

    last_sold = {}
    for o in orders:
        if o["side"] == "sell":
            last_sold[o["symbol"]] = market.to_et(o["submitted_at"])
    cooldown = timedelta(minutes=config.COOLDOWN_MINUTES)
    candidates = sorted(
        (s for s, g in sigs.items()
         if g.buy and s not in held and now - last_sold.get(s, now - 2 * cooldown) >= cooldown),
        key=lambda s: -sigs[s].rank,
    )
    for s in candidates:
        slots = config.MAX_POSITIONS - len(held)
        spend = round(cash / slots, 2) if slots > 0 else 0
        if spend < config.MIN_ORDER_DOLLARS:
            break
        if dry_run:
            record(event="buy", symbol=s, dollars=spend, dry_run=True)
            held[s] = {"qty": 0}
            cash -= spend
            continue
        o = broker.wait_filled(broker.buy(s, spend))
        if o.get("filled_avg_price"):
            cash -= float(o["filled_qty"]) * float(o["filled_avg_price"])
            held[s] = {"qty": float(o["filled_qty"])}
        record(event="buy", symbol=s, dollars=spend, status=o["status"],
               price=o.get("filled_avg_price"), qty=o.get("filled_qty"))

    record(event="end", virtual_cash=round(cash, 4), held=list(held), jev_calls=len(answers),
           jev_cost=round(jev_cost, 6))
    return log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="decide but place no orders")
    ap.add_argument("--at", help="pretend it is this ET time (YYYY-MM-DDTHH:MM); implies --dry-run")
    args = ap.parse_args()

    if args.at:
        now, dry_run = datetime.fromisoformat(args.at).replace(tzinfo=market.ET), True
    else:
        if not broker.clock()["is_open"]:
            print("Market closed; nothing to do.")
            return
        now, dry_run = datetime.now(market.ET).replace(second=0, microsecond=0), args.dry_run

    log = run(now, dry_run)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, f"{now.date().isoformat()}.jsonl"), "a") as f:
        for entry in log:
            f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    main()
