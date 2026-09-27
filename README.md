# DAYTRADES

**An experiment: give Jev, TypeSafe's "System One" decision model accessed through OpenRouter, a tiny real account ($10). Let it make thousands of fast hold/sell and buy/pass decisions every trading day, and measure whether that beats doing nothing.**

People have already tried giving an AI some money and letting it do what it wants, and some built AI day traders to try to earn an income. Those bots almost always use chat LLMs (big, slow, expensive models that write text), so they only make a few decisions. This project goes the other way. **Jev writes no text at all. It's a "smart `if` statement":** you give it data plus typed questions, and it returns typed answers with probabilities in roughly 100–900 ms, for about **$0.00002 per call**. At that price, the bot can re-judge every position and every candidate every minute of the trading day for pocket change.

The question being tested:

> Can a fast, cheap decision model re-checking hold/sell and buy/pass decisions constantly beat just holding the market once fees, AI cost and trading rules are counted?

---

## 1. What Jev is (and why it fits this)

| | Chat LLM (GPT, Claude, …) | **Jev** |
|---|---|---|
| Output | Generated text you have to parse | **Typed answers + probabilities**, valid by construction |
| Speed | Seconds | ~70–900 ms |
| Price | $ per million tokens, output costs more | **$0.042 / 1M input tokens, output free** |
| Good at | Writing, reasoning, math | Fast judgment: classifying, routing, ranking, yes/no |
| Bad at | Cost at high volume | **Math, counting, comparing dates, writing text** |

Jev answers three kinds of question, and all three can be asked in **one call** (they're evaluated in parallel against the same data):

| Primitive | Asks | Returns | Use in this bot |
|---|---|---|---|
| `choice` | Pick one option from a list | winning option + probability for each + confidence | `HOLD` vs `SELL`, `BUY` vs `PASS` |
| `score` | Where does this sit on an ordered scale? | position on the scale (can be fractional) + probabilities | "How strong is this setup?" weak / ok / strong |
| `noul` | How likely is this statement true? | P(yes), 0–1 | "Is there bad news about this stock?" |

**How to think in Jev**, from TypeSafe's docs:
1. **Make questions atomic.** Each one should be something an expert could answer in seconds.
2. **Ask everything at once.** Several questions in one call is much cheaper than several calls.
3. **Smart values, dumb glue.** Jev returns the judgments, and ordinary Python combines them into the final action, e.g. `buy_score = 0.5*setup + 0.3*momentum - 0.4*bad_news`.

**The big design consequence:** Jev is bad at arithmetic. **Python does all the number-crunching** (price change, volume vs. average, distance from VWAP, P/L). It hands Jev the results as plain words and numbers ("up 2.3% in 15 min, volume 3× normal, position +1.8%"), and Jev only makes the *judgment call*. Jev's biggest advantage over a plain rules bot is probably **reading unstructured text such as news headlines**, so the design includes headlines in the data it sees.

---

## 2. Accessing Jev: OpenRouter, not TypeSafe directly

**All Jev calls go through OpenRouter.** We use an OpenRouter API key (`OPENROUTER_API_KEY`), and costs are billed to the OpenRouter account. We do **not** use TypeSafe's own API or the `typesafe-sdk` package.

Important details:
- Jev on OpenRouter uses the **Decisions API, not chat completions.** The usual `openai`/chat-completions SDKs **will not work.** A plain HTTP POST (`requests`, or even the Python standard library) is all that's needed.
- **Endpoint:** `POST https://openrouter.ai/api/alpha/decisions` (also offered: a TypeSafe-compatible `POST https://openrouter.ai/api/v1/systemone`). It's labeled **alpha/beta**, so expect changes.
- **Model id:** `typesafe/jev-1.13` (or the alias `~typesafe/jev-latest`).
- **Response:** `answers` (one per question), `usage` (tokens **and `cost` in dollars**, which we log on every call), `provider`, `model`, `id`.

Minimal call (standard library only):

```python
import json, os, urllib.request

def decide(state, questions, model="typesafe/jev-1.13"):
    req = urllib.request.Request(
        "https://openrouter.ai/api/alpha/decisions",
        data=json.dumps({"model": model, "state": state, "questions": questions}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

state = """AAPL | held position: bought $2.50 at 227.10, now 229.40 (+1.0%)
Last 15 min: +0.4%, volume 0.8x normal, price 0.3% above VWAP, RSI 64
Headlines (last hour): none"""

resp = decide(state, {
    "action":   {"type": "choice", "instructions": "Should a short-term day trader keep or exit this position now?",
                 "criteria": {"HOLD": "Trend intact, no reason to exit",
                              "SELL": "Momentum fading, risk rising, or gain worth locking in"}},
    "momentum": {"type": "score", "instructions": "How strong is the short-term momentum?",
                 "criteria": ["fading", "flat", "strong"]},
    "bad_news": {"type": "noul", "instructions": "Do the headlines contain news likely to push this stock down today?"},
})
a = resp["answers"]
print(a["action"]["choice"], a["action"]["confidence"], a["momentum"]["score"],
      a["bad_news"]["noul"], resp["usage"]["cost"])
```

> ✅ **Verified in Phase 0 (`src/hello_jev.py`).** 3 hand-written positions, 3 questions each: every answer was served by `TypeSafe` (model `typesafe/jev-1.13-20260917`) with the requested type. Each call used ~470 input tokens and took 340–600 ms. The 3 calls cost **$0.000059** in total, about **$0.00002 per call**. Confirmed fields: `answers.<name>.choice / .probabilities / .confidence` (choice), `.score / .legend / .probabilities / .confidence` (score, fractional e.g. 1.99), `.noul` (noul), `usage.cost`, `provider`, `model`, `id`.
>
> | Test position | Action | Momentum (0–2) | Bad news P(yes) |
> |---|---|---|---|
> | Collapsing (guidance cut, CFO resigns) | SELL, confidence 0.99 | 0.03 | 0.96 |
> | Strong (wins contract, +1.8%) | HOLD, confidence 0.62 | 1.99 | 0.05 |
> | Boring (flat, no news) | HOLD, confidence 0.40 | 0.99 | 0.04 |
>
> **Lesson:** the atomic questions (momentum, bad news) were near-certain, but the bundled HOLD/SELL question was unsure on the calm cases. One likely reason is that its SELL option mixed three reasons, including "gain worth locking in", which partly matches any winning position. This backs the "smart values, dumb glue" rule: decide the action in Python from atomic signals, and leave profit-taking to the hard take-profit rule in code.

---

## 3. The core loop: two lists, two questions

| List | Contains | Jev question each cycle | Answers |
|---|---|---|---|
| **Holdings** | What the account owns right now | "Keep or exit?" | `HOLD` / `SELL` |
| **Watchlist** | 10–30 liquid tickers it could buy | "Enter now or not?" | `BUY` / `PASS` |

Each ticker gets **one Jev call per cycle** asking a few atomic questions at once (a `choice` for the action, a `score` or two for strength, a `noul` for bad news). Python then combines the answers and applies the risk rules.

```
            ┌──────────────────────────────────────────────┐
            │          SCHEDULER  (every 1–5 min)          │
            └───────────────┬──────────────────────────────┘
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
 ┌─────────────────┐                 ┌─────────────────┐
 │  HOLDINGS LOOP  │                 │ WATCHLIST LOOP  │
 └────────┬────────┘                 └────────┬────────┘
          ▼                                   ▼
 ┌───────────────────────────────────────────────────────┐
 │ PYTHON: fetch prices + headlines, compute indicators, │
 │ write them as a short plain-text "state"              │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │ JEV via OpenRouter Decisions API                      │
 │ choice(HOLD/SELL or BUY/PASS) + score(s) + noul(s)    │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │ PYTHON "glue": combine answers → action               │
 │ act only if confidence ≥ threshold                    │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │ RISK GUARDRAILS (hard rules, Jev cannot override)     │
 └───────────────────────────┬───────────────────────────┘
                             ▼
 ┌───────────────────────────────────────────────────────┐
 │ BROKER API (paper first → real $10)  →  LOG everything│
 └───────────────────────────────────────────────────────┘
```

### Using Jev's probabilities honestly
Jev says *how sure it is*, and the bot should use that:
- **Confidence gate:** only trade when `confidence ≥ 0.75` (tune this). "Torn" answers become `HOLD`/`PASS`.
- **Tie-break by ranking:** if several `BUY`s pass the gate, buy only the top one or two by combined score. The account is tiny.
- **Asymmetric thresholds:** exiting should be easier than entering, e.g. SELL at ≥ 0.6 but BUY at ≥ 0.8.

### Risk guardrails (plain code; Jev can't override them)
- Max % of the account in one position (e.g. 50% with $10, so at most 2 positions)
- Hard stop-loss / take-profit per position (e.g. −2% / +3%), checked in code every cycle whatever Jev says
- Daily loss limit: down X% today → stop until tomorrow
- Cooldown: no re-buying a ticker within N minutes of selling it
- Flat by market close (it's a *day* trader, so no overnight positions)
- Respect regulatory limits (section 5)
- **Kill switch:** one command sells everything and stops the bot

---

## 4. Cost: why Jev makes "constantly running" realistic

At ~$0.000018–0.00002 per call (about 400–450 input tokens, 3 questions):

| Setup | Calls / day | Jev cost / day | per month (~21 days) |
|---|---|---|---|
| 25 tickers, every 5 min (78 cycles) | ~1,950 | **~$0.04** | ~$0.80 |
| 25 tickers, every 1 min (390 cycles) | ~9,750 | **~$0.20** | ~$4 |
| Crypto, 10 tickers, every 1 min, 24/7 | ~14,400 | **~$0.29** | ~$9 |

Jev is cheap, but **on a $10 account even $0.04/day is 0.4% of the account every day** (over 8% a month). The bot has to earn more than that just to break even, so AI cost gets **its own line on the scorecard**, read from `usage.cost` on every response. For the $10 live run, start slow (5-minute cycles, a small watchlist). The fast version belongs on paper.

---

## 5. Reality check for a $10 account (read before going live)

- **Pattern Day Trader (PDT) rule (US).** A *margin* account under $25,000 is limited to 3 day trades in any rolling 5 business days. (FINRA has been working on changing this rule. Check what's in effect when you run the test.)
- **Cash accounts** avoid PDT, but sale proceeds take a day to settle (T+1). Buying with unsettled money and then selling can trigger *good-faith violations*, and several of those get the account restricted.
- **Crypto trades 24/7 with no PDT rule.** For a true "running constantly" live test with $10, crypto through a broker API may be the realistic market. Watch spreads and fees closely.
- **Paper trading** is where the high-volume stock version can run freely.
- **Spreads and fees:** a few cents per trade is a big percentage of $10.
- **Expectations:** most day traders lose money, and $10 will not produce an income even if it works. The goal is to *measure whether this approach has an edge* before scaling.

**Plan:** high-volume version on **paper**; **$10 live** under real constraints (limited stock day trades, or crypto).

---

## 6. Test plan

### Phase 0: Hello Jev (no money)
- Get an OpenRouter key, make one Decisions API call, print the raw response, confirm field names and per-call cost.
- Feed it 5–10 hand-written "states" (a clearly collapsing stock, a clearly strong one, a boring one) and check the `HOLD`/`SELL` answers make sense.

### Phase 1: Replay (no money)
- Replay a few past trading days of 1-minute bars through the full loop (data → Jev → glue → guardrails → simulated fills).
- Compare against baselines: **(a) hold SPY**, **(b) a rules-only bot with no Jev** (e.g. "buy if up 1% in 15 min on 2× volume, exit at ±2%"). If Jev can't beat (b), it isn't adding value.

### Phase 2: Paper trading (2–4 weeks)
- Run live during market hours on a free paper account (e.g. Alpaca), simulating $10 (and optionally $1,000 to remove rounding and fractional-share effects).

### Phase 3: Real $10
- Same code, live keys, every guardrail on, fixed period (e.g. 4 weeks), no strategy changes mid-run.

### Scorecard
| Metric | Why |
|---|---|
| Net P/L after fees **and Jev cost** | The only number that really matters |
| Return vs. holding SPY, and vs. the rules-only bot | Did Jev add anything? |
| Win rate, average win / average loss | Real edge, or luck? |
| Max drawdown | How bad did it get? |
| Trades per day | Did "high volume" actually happen? |
| Jev cost per day and per trade | From `usage.cost` |
| Calibration: when Jev said 0.8 confidence, how often was it right? | Are its probabilities meaningful for markets? |
| % of Jev decisions blocked by guardrails | Is Jev or the rulebook doing the work? |

---

## 7. Suggested repo layout (to build next)

```
DAYTRADES/
├── README.md            ← this file
├── .env                 ← OPENROUTER_API_KEY, broker keys (gitignored, never committed)
├── config.yaml          ← watchlist, questions, thresholds, guardrail limits, cycle speed, paper/live
├── src/
│   ├── jev.py           ← OpenRouter Decisions API client + cost tracking
│   ├── questions.py     ← the Jev question sets (holdings, watchlist)
│   ├── data.py          ← prices, indicators, headlines → plain-text "state"
│   ├── watchlist.py     ← picks candidate tickers
│   ├── glue.py          ← combine Jev answers → action (smart values, dumb glue)
│   ├── risk.py          ← guardrails + kill switch
│   ├── broker.py        ← orders (paper/live)
│   ├── logger.py        ← every decision, answer, order, fill, cost (SQLite/CSV)
│   └── main.py          ← scheduler loop
├── backtest/            ← replay past days
└── reports/             ← daily scorecards
```

## 8. Open questions
- Stocks (PDT-limited at $10) or crypto (24/7, no PDT) for the live run?
- Cycle speed: 1, 5 or 15 minutes? Faster means more decisions and more Jev cost.
- Should headlines be included from day one, or should we start with numbers only and add them later to see whether they help?
- Which broker/data feed (Alpaca's free paper account and data is the default assumption)?
- How far does Jev's probability calibration carry over to market questions, where the "right answer" is genuinely uncertain? This is what the experiment finds out.

---

## Sources
- OpenRouter Jev guide: https://openrouter.ai/docs/guides/community/jev
- OpenRouter Jev 1.13 model page (pricing): https://openrouter.ai/typesafe/jev-1.13
- OpenRouter "What is Jev?": https://openrouter.ai/blog/insights/what-is-jev/
- Working OpenRouter example: https://github.com/vinaychawla-ops/jev-openrouter-example
- TypeSafe, Introducing System One & Jev: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- TypeSafe docs, primitives and patterns: https://docs.typesafe.ai/primitives, https://docs.typesafe.ai/patterns
- Flavio Copes' walkthrough: https://flaviocopes.com/jev/

*This is an experiment, not financial advice. Only put in money you're fine losing entirely.*
