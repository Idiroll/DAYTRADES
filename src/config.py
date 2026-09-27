"""Every tunable number in one place, so experiments change settings here, not code."""

# Liquid, commission-free, fractional-share-friendly names. Liquid = tight spreads.
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL"]
BENCHMARK = "SPY"

STARTING_CASH = 10.00

# Decision cycle (US Eastern time). Jev is asked about every ticker every CYCLE_MINUTES.
CYCLE_MINUTES = 5
FIRST_CYCLE = "09:45"      # skip the chaotic first 15 minutes
LAST_ENTRY = "15:30"       # no new buys after this
FLATTEN_AT = "15:55"       # day trader: everything sold before the close

# Hard risk rules. Checked every minute in code; Jev cannot override them.
MAX_POSITIONS = 2          # $10 split at most two ways
STOP_LOSS = -0.02          # -2%
TAKE_PROFIT = 0.03         # +3%
COOLDOWN_MINUTES = 30      # no re-buying a ticker this soon after selling it
SLIPPAGE = 0.0005          # 0.05% lost on every buy and every sell (spread + fill quality)

# Jev
JEV_MODEL = "typesafe/jev-1.13"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_WORKERS = 8            # parallel calls during replay
MAX_JEV_COST = 1.00        # replay refuses to spend more than this (USD)

# Threshold sweep for the Jev strategy (see strategies.py for what each one means).
BUY_THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9]
SELL_THRESHOLDS = [0.5, 0.7, 0.9]
