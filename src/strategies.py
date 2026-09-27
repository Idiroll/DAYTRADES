"""The questions Jev answers, and the "dumb glue" that turns answers into actions.

Jev is asked the same atomic questions about every ticker every cycle, whether
we hold it or not. Position-specific decisions (stop-loss, take-profit, how much
to buy) are plain code. Keeping the state position-independent also means each
answer can be cached and reused across every threshold we test.
"""

QUESTIONS = {
    "momentum": {
        "type": "score",
        "instructions": "How strong is this stock's short-term upward momentum right now?",
        "criteria": ["fading", "flat", "strong"],
    },
    "overextended": {
        "type": "noul",
        "instructions": "Has this stock moved so far so fast today that a pullback in the next 30 minutes is likely?",
    },
    "bad_news": {
        "type": "noul",
        "instructions": "Do the headlines contain news likely to push this stock down today?",
    },
    "good_news": {
        "type": "noul",
        "instructions": "Do the headlines contain news likely to push this stock up today?",
    },
}


class Signal:
    def __init__(self, buy=False, sell=False, rank=0.0):
        self.buy, self.sell, self.rank = buy, sell, rank


def jev_strategy(buy_threshold, sell_threshold):
    """BUY when Jev's probability that momentum is 'strong' >= buy_threshold (and no red flags).
    SELL when its probability that momentum is 'fading' >= sell_threshold, or bad news appears."""

    def signal(features, answers):
        probs = answers["momentum"]["probabilities"]
        p_strong, p_fading = probs.get("2", 0), probs.get("0", 0)
        bad = answers["bad_news"]["noul"]
        good = answers["good_news"]["noul"]
        stretched = answers["overextended"]["noul"]
        return Signal(
            buy=p_strong >= buy_threshold and bad < 0.5 and stretched < 0.5,
            sell=p_fading >= sell_threshold or bad >= 0.7,
            rank=p_strong + 0.2 * good,
        )

    signal.name = f"jev buy>={buy_threshold} sell>={sell_threshold}"
    signal.uses_jev = True
    return signal


def rules_strategy():
    """No AI at all: classic momentum rules. Jev has to beat this to be worth anything."""

    def signal(f, answers=None):
        return Signal(
            buy=f["chg15"] >= 0.003 and f["vol_ratio"] >= 1.3 and f["vs_vwap"] > 0 and f["rsi"] < 75,
            sell=f["chg15"] <= -0.003 or f["vs_vwap"] < 0,
            rank=f["chg15"],
        )

    signal.name = "rules-only (no AI)"
    signal.uses_jev = False
    return signal
