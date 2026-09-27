# Experiment 2: Jev reads headlines (2026-06-18 to 2026-09-25)

2,202 headline-stock events, 69 trading days, Jev cost $0.038. Jev rated each headline's likely impact (strongly negative to strongly positive) and whether it was material. The measured move is the next 30/60/120 min, minus SPY's move over the same window (for SPY headlines, SPY's own move).

```
Jev: 2202 events, 2201 new calls (~$0.0440)
2202 events answered, Jev cost $0.0380, 0 failed
Material (P>=0.5): 439 of 2202

ALL headlines by Jev impact (next 30 min, vs SPY)
  strongly negative                  n=7     avg -0.014%  t=-0.2
  somewhat negative                  n=520   avg -0.020%  t=-1.5
  neutral                            n=1019  avg +0.008%  t=+0.8
  somewhat positive                  n=636   avg +0.005%  t=+0.3
  strongly positive                  n=20    avg -0.037%  t=-0.3

MATERIAL headlines by Jev impact (next 30 min, vs SPY)
  strongly negative                  n=5     avg -0.106%  t=-1.6
  somewhat negative                  n=113   avg -0.054%  t=-1.5
  neutral                            n=87    avg -0.005%  t=-0.1
  somewhat positive                  n=223   avg -0.029%  t=-1.0
  strongly positive                  n=11    avg -0.269%  t=-1.5

ALL headlines by Jev impact (next 60 min, vs SPY)
  strongly negative                  n=7     avg -0.104%  t=-0.7
  somewhat negative                  n=520   avg -0.034%  t=-1.6
  neutral                            n=1019  avg +0.027%  t=+1.8
  somewhat positive                  n=636   avg +0.055%  t=+2.6  <- |t|>2
  strongly positive                  n=20    avg +0.031%  t=+0.2

MATERIAL headlines by Jev impact (next 60 min, vs SPY)
  strongly negative                  n=5     avg -0.302%  t=-3.5
  somewhat negative                  n=113   avg -0.051%  t=-0.8
  neutral                            n=87    avg +0.017%  t=+0.3
  somewhat positive                  n=223   avg +0.046%  t=+1.1
  strongly positive                  n=11    avg -0.287%  t=-1.2

ALL headlines by Jev impact (next 120 min, vs SPY)
  strongly negative                  n=7     avg +0.059%  t=+0.3
  somewhat negative                  n=520   avg -0.017%  t=-0.7
  neutral                            n=1019  avg +0.021%  t=+1.1
  somewhat positive                  n=636   avg +0.092%  t=+3.4  <- |t|>2
  strongly positive                  n=20    avg -0.129%  t=-0.6

MATERIAL headlines by Jev impact (next 120 min, vs SPY)
  strongly negative                  n=5     avg -0.184%  t=-1.3
  somewhat negative                  n=113   avg +0.000%  t=+0.0
  neutral                            n=87    avg +0.074%  t=+0.9
  somewhat positive                  n=223   avg +0.087%  t=+1.6
  strongly positive                  n=11    avg -0.618%  t=-2.0

first half: positive vs negative material (next 60 min, vs SPY)
  positive                           n=119   avg +0.033%  t=+0.5
  negative                           n=75    avg -0.193%  t=-2.9  <- |t|>2

second half: positive vs negative material (next 60 min, vs SPY)
  positive                           n=115   avg +0.027%  t=+0.8
  negative                           n=43    avg +0.168%  t=+1.5

Rule 'buy on material positive headline, sell 60 min later', after costs: 234 trades, avg -0.070% per trade, t=-1.7
Move in the 15 min BEFORE positive material headlines: avg -0.015% (big = news already priced in by the time it's published)


SPY only, 1st half (next 120 min, vs SPY)
  somewhat negative                  n=127   avg -0.017%  t=-0.5
  neutral                            n=247   avg -0.057%  t=-2.2  <- |t|>2
  somewhat positive                  n=70    avg +0.094%  t=+2.1  <- |t|>2

SPY only, 2nd half (next 120 min, vs SPY)
  somewhat negative                  n=124   avg -0.039%  t=-1.9
  neutral                            n=276   avg -0.009%  t=-0.7
  somewhat positive                  n=77    avg +0.016%  t=+0.7

single stocks (vs SPY), 1st half (next 120 min, vs SPY)
  somewhat negative                  n=153   avg -0.021%  t=-0.3
  neutral                            n=257   avg +0.162%  t=+2.8  <- |t|>2
  somewhat positive                  n=235   avg +0.090%  t=+1.5

single stocks (vs SPY), 2nd half (next 120 min, vs SPY)
  somewhat negative                  n=116   avg +0.012%  t=+0.2
  neutral                            n=239   avg -0.014%  t=-0.3
  somewhat positive                  n=254   avg +0.116%  t=+3.1  <- |t|>2

Single stocks, buy on any positive headline, hold 120 min, after costs: (509, -5.653460008990951e-05, -0.16474397916693392)
```

## Takeaways
1. **There's a small, real-looking directional signal**, unlike Experiment 1. On single stocks, headlines Jev called "somewhat positive" were followed by about +0.09% to +0.12% versus SPY over 2 hours, in both halves of the period (t = 1.5 and 3.1). On SPY, positive macro headlines beat negative ones in both halves.
2. **It's about as big as the assumed trading cost.** At 0.05% slippage per side (0.10% per round trip), "buy on a positive headline, hold 2 hours" nets about 0.00% per trade (509 trades).
3. **The "material" filter and the "strong" ratings didn't help.** Their samples are small (5–20 events) and they flipped between halves, so they're noise.
4. **What decides it is the real trading cost.** 0.05% per side is a cautious guess. Live spreads on these mega-caps are often around 0.01%. Live paper fills will show the true cost, and if it's well under 0.05% per side, this edge might survive.
