# DAYTRADES

**An experiment: give a very cheap AI model (JEV) a tiny amount of real money ($10) and let it day trade all day, making many small, fast decisions, to see what happens.**

People have already tried handing an AI some money and letting it do what it wants. Some of them built AI day traders to try to earn an income. This project goes further in one direction: **volume and cost.** Most AI trading bots use expensive frontier models and make only a few trades. This one uses JEV, a model cheap enough to call thousands of times a day. It asks simple, narrow questions over and over instead of a few big, open-ended ones.

The question being tested:

> Can a very cheap model, making a large number of simple decisions (hold/sell and buy/pass), beat just holding the market once fees, model costs and trading rules are counted?

---

## The core idea: two lists, two questions

The AI never gets an open-ended "what should I do?" question. It only answers two narrow ones, again and again:

| List | Contains | Question asked each cycle | Allowed answers |
|---|---|---|---|
| **Holdings** | Stocks the account owns right now | "Keep this position or exit?" | `HOLD` / `SELL` |
| **Watchlist** | Stocks it could buy | "Enter a position now or not?" | `BUY` / `PASS` |

Each answer also returns a **confidence (0–1)** and a **one-line reason**. These are logged so the results can be studied later.

Narrow questions keep each call small and cheap. They are also easy to check, and they make it hard for the model to do something unexpected.

---

## Architecture

```
            ┌───────────────────────────────────────────────┐
            │                SCHEDULER (loop)               │
            │   runs every N seconds during market hours    │
            └───────────────┬───────────────────────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
 ┌─────────────────┐                 ┌─────────────────┐
 │  HOLDINGS LOOP  │                 │ WATCHLIST LOOP  │
 │  per position:  │                 │  per candidate: │
 │  HOLD / SELL    │                 │  BUY / PASS     │
 └────────┬────────┘                 └────────┬────────┘
          │  market snapshot (price, % change, volume,
          │  short-term indicators, position P/L)
          ▼                                   ▼
 ┌───────────────────────────────────────────────────────┐
 │                 JEV  (the cheap LLM)                  │
 │  small prompt in → strict JSON out                    │
 │  {"action":"SELL","confidence":0.72,"reason":"..."}   │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │        RISK GUARDRAILS  (plain code, not AI)          │
 │  can block or override any AI decision                │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │  BROKER API  (paper account first, then real $10)     │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │  LOG  every decision, order, fill, and API cost       │
 └───────────────────────────────────────────────────────┘
```

### Components

1. **Market data feed.** Recent price bars (1-minute or 5-minute), volume and a few simple indicators (e.g. RSI, VWAP distance, % move today). Code computes these numbers before JEV sees them, so the model interprets numbers but never does the math.
2. **Watchlist builder.** Runs a few times a day, not every cycle. It picks 10–30 liquid, low-priced or fractional-share-friendly tickers (e.g. top volume movers or a fixed list of ETFs and large caps). Sticking to liquid names keeps bid/ask spreads from eating a $10 account.
3. **JEV decision calls.** One small prompt per ticker per cycle, and the model must answer in strict JSON. If the output doesn't parse, the action is `HOLD` or `PASS`: do nothing.
4. **Risk guardrails (the most important part).** These are hard-coded rules the AI cannot override:
   - Max % of the account in any one position (e.g. 25%)
   - Stop-loss / take-profit per position (e.g. −3% / +5%)
   - Daily loss limit: if the account is down X% today, stop trading until tomorrow
   - Minimum confidence to act (e.g. only act when confidence ≥ 0.65)
   - Cooldown: no re-buying a ticker within N minutes of selling it
   - Respect regulatory limits (see below)
   - **Kill switch:** one command that flattens every position and stops the bot
5. **Broker.** An API-first, commission-free broker with fractional shares and a free paper-trading account (e.g. Alpaca).
6. **Logger / scorecard.** Every call is recorded with timestamp, ticker, inputs, AI answer, what the guardrails did, order result, and the token cost of the call. This log is the real product of the experiment.

---

## Reality check for a $10 account (read before going live)

These rules shape the design more than the AI does:

- **Pattern Day Trader (PDT) rule (US).** A *margin* account under $25,000 is limited to 3 day trades in any rolling 5 business days. "A TON of day trades" with real money is not allowed in a normal US margin account. (FINRA has been working on changing this rule. Check what's in effect when you run the experiment.)
- **Cash accounts** avoid PDT, but sale proceeds take a day to settle (T+1). Buying with unsettled money and then selling can trigger *good-faith violations*, and several of those get the account restricted.
- **Crypto trades 24/7 with no PDT rule.** For a true "running all day, constantly trading" test with $10, crypto (e.g. BTC/ETH through the same broker API) may be the more realistic live market. Spreads and fees matter even more there.
- **Paper trading has no such limits in practice.** The high-frequency version of the idea can be tested there freely.
- **Fees and spreads.** On $10, a few cents of spread per trade is a large percentage. Log it.
- **Expectations.** Most human day traders lose money, and $10 will not produce an income even if the bot does well. The goal is to *measure whether the approach has an edge*. If it does, you can scale up later.

**Practical plan:** run the high-volume version on **paper**, and run the **$10 live** version under the real constraints (limited stock day trades, or crypto).

---

## Cost model (why JEV)

The whole idea depends on AI calls being almost free. Rough estimate:

```
calls per day   = (holdings + watchlist size) × cycles per day
                = e.g. (5 + 20) × (6.5 hrs × 60 / 5-min cycle = 78)  ≈ 1,950 calls/day
tokens per call ≈ 400 in + 50 out
daily AI cost   = calls × tokens × JEV price per token
```

Put JEV's actual per-token prices into the formula. The rule for the experiment:
**daily AI cost must stay well below the expected daily profit**, or the bot can't be profitable even when its trades are good. With a $10 account this is a very high bar, so track **AI cost as its own line** on the scorecard.

---

## Test plan

### Phase 0: Build and replay (no money)
- Wire up data → JEV → guardrails → logger.
- **Replay** a few past trading days of 1-minute data through the bot to check the plumbing and the cost per day.
- Baseline: compare against simple rule-only bots (e.g. "buy if up 1% in 15 min, sell at ±2%") and against **doing nothing / holding SPY**.

### Phase 1: Paper trading (2–4 weeks)
- Run live during market hours on a paper account with a simulated $10 (and optionally $1,000 to get past rounding and fractional-share effects).
- No real money until this phase ends.

### Phase 2: Real $10
- Same code with live keys, and all guardrails turned on.
- Run for a fixed period (e.g. 4 weeks) and don't change the strategy mid-run.

### Scorecard (what "success" means)
| Metric | Why |
|---|---|
| Net P/L after fees **and** AI cost | The only number that really matters |
| Return vs. holding SPY over the same period | Did it beat doing nothing? |
| Win rate and average win / average loss | Is there an edge, or just luck? |
| Max drawdown | How bad did it get? |
| Trades per day | Did the "high volume" idea actually happen? |
| AI cost per trade | Is JEV really cheap enough? |
| % of AI decisions blocked by guardrails | Is the AI or the rulebook doing the work? |

---

## Suggested repo layout (to build next)

```
DAYTRADES/
├── README.md            ← this file
├── config.yaml          ← watchlist settings, guardrail limits, cycle speed, paper/live switch
├── src/
│   ├── data.py          ← market data + indicator calculation
│   ├── watchlist.py     ← picks candidate tickers
│   ├── brain.py         ← JEV prompts + strict JSON parsing
│   ├── risk.py          ← guardrails (hard rules, kill switch)
│   ├── broker.py        ← order placement (paper/live)
│   ├── logger.py        ← decision + cost log (CSV/SQLite)
│   └── main.py          ← the scheduler loop
├── backtest/            ← replay past days through the bot
└── reports/             ← daily scorecards
```

## Open questions
- Which JEV model/endpoint, and what are its exact per-token prices and rate limits?
- Stocks (PDT-limited with $10) vs. crypto (24/7, no PDT) for the live run?
- How fast should a cycle be: 1 min, 5 min, 15 min? Faster means more trades and higher AI cost.
- Should the model also see news headlines, or only price/volume numbers? (Starting with numbers only keeps it cheap.)

---

*This is an experiment, not financial advice. Only put in money you're fine losing entirely.*
