# KIMI K3 — Autonomous Crypto Futures Trading System

**K3** is an original trading system for Binance USDT-M perpetual **scalping and day trading**
on the top-10 crypto futures by volume. Signal/paper only — it never places orders.

Lineage: it absorbs the DNA of
[ict-quantrex-cursor](https://github.com/talentsolutionsmyanmar-max/ict-quantrex-cursor)
(ICT liquidity concepts, fixed-fractional risk kernel, scale-out ladder, market gates) and
[quantrex-Fable5](https://github.com/talentsolutionsmyanmar-max/quantrex-Fable5)
(ensemble fusion gating, provenance doctrine) — then goes further with its own architecture.

## What K3 adds on top of the lineage

| K3 original | Why it matters |
|---|---|
| **Structure state machine** — BOS / CHoCH / displacement / order blocks | The lineage detected levels; K3 tracks *market structure itself* |
| **5-group signed factor fusion** (Structure .30 / Liquidity .20 / Momentum .20 / Volatility .15 / Positioning .15) | Every bar gets a calibrated 0–100 K3 score per direction, not a binary signal |
| **Positioning intelligence** — funding z-score (30d history), OI delta, taker buy/sell flow | Knows when a trade is *crowded* — blocks or fades it |
| **Tiered decisions** — ACTIVE / WATCH / STANDBY + conviction-scaled risk (0.75x / 1.0x / 1.25x) | Position size follows evidence, not hope |
| **Funding-aware backtester** — 8h funding drag, signal-flip early exit, per-tier P&L attribution | Backtests that behave like real perp trading |
| **Walk-forward research mode** — train 60% / OOS 40% with a train-gate | Kills parameter combos that only look good in-sample |
| **Look-ahead regression harness** — `leaktest` must lose on random walks | Any backtest number that can't survive this is not shipped |
| **Universe screener** — 75+ perps ranked by range / tape / drift / funding, not just volume | Finds game-changer pairs the volume top-10 misses; candidates are backtested before promotion |

## Run it

```bash
pip install -r requirements.txt

python k3.py top10                              # live top-10 futures universe
python k3.py universe                           # game-changer screener (all USDT-M perps)
python k3.py scan --profile both                # live setups, both profiles
python k3.py backtest --profile day --limit 1500
python k3.py research --profile scalp           # walk-forward validation
python k3.py leaktest                           # random-walk look-ahead regression (must lose)
python k3.py replay                             # order-flow overlay validation (accruing)
python k3.py scan --symbols BTCUSDT SOLUSDT --capital 25000 --profile day
```

## The two profiles

| | SCALP (experimental ⚠) | DAY (validated ✓) |
|---|---|---|
| TF / context | 5m / 15m | 15m / 1h |
| Stop | 1.3 × ATR | 1.8 × ATR |
| TP ladder | 0.8/1.6/2.6 R — 50/30/20 | 1/2/3 R — 50/30/20 |
| Max hold | 24 bars (2h) | 48 bars (12h) |
| Sweep filter | volume ≥ 1.15× | off |
| Tiers (ACTIVE/WATCH) | 64 / 52 | 62 / 50 |

Tiers are **empirically calibrated**: on the majors the K3 composite's q95 ≈ 50–52 and
q99 ≈ 61–63, so ACTIVE fires on roughly the top 1% of bars — selective by construction.

## Validation results — the honest baseline (2026-07-26, post Fable5 audit)

**⚠ The earlier DAY claim (+$2,942, 65.9% win) was retracted.** A Fable5 audit found two
look-ahead leaks in `structure.py` (FVG flagged 2 bars into the future via `shift(-2)`;
swing levels visible before their 2-bar confirmation). The audit's random-walk test proved
the old engine profited on coin flips (+$1,578 on 8 seeds) — the classic signature of
look-ahead bias. Both leaks are now fixed (causal 3-candle FVG, confirmation-delayed
swings), and the random-walk regression test (`python3 k3.py leaktest`) is permanent:
**post-fix the engine loses on all random-walk seeds, as a correct backtester must.**

**True DAY baseline (leak-free, honest costs 0.055% taker + ATR stop-gap slippage,
1500 bars × 10 symbols, $10k, funding):** 508 trades, 51.3% win, **−$7,056 net**.
ACTIVE-tier-only variant: 126 trades, 49.1% win, −$3,253. On this 15-day single-regime
sample the leak-free DAY stack does **not** beat costs — that is the true starting point,
and every future improvement is measured against it. Signal quality concentrates in the
ACTIVE tier and per-session attribution (`pnl_by_session`) now shows where.

**SCALP profile — honest failure, still documented on purpose.** Raw backtest: −$3,650.
Walk-forward research: **no combo survived out-of-sample**. Additionally, SCALP entries
are now kill-zone-gated in the backtester for live-engine parity. Ships as experimental.

**Doctrine:** K3 numbers are believable only because they are now *mechanically*
verifiable — `leaktest` must pass, walk-forward gates research, and any claim that
can't survive both is not shipped. That is the Fable5 provenance doctrine applied
to K3 itself, not just its failures.

## Architecture

```
k3/
  config.py     # risk kernel + SCALP/DAY profiles + fusion weights
  data.py       # Binance futures API: top10, klines(+taker flow), funding hist/z, OI, indicators
  structure.py  # swings (confirmation-delayed), BOS/CHoCH, displacement, causal FVG, PD, OTE, sweeps, OBs
  signals.py    # 5-group signed scorers + composite K3 score + tiers + positioning overlay
  risk.py       # conviction-scaled sizing, TP ladder, portfolio caps
  engine.py     # per-symbol setup builder (structure → fusion → gates → trade plan)
  backtest.py   # leak-free event-driven backtester, KZ-gated SCALP, per-session P&L, honest costs
  research.py   # walk-forward grid validation with OOS honesty gate
  killzones.py  # ICT kill-zone session clock (UTC)
  livefeed.py   # 24/7 websocket engine: 1s marks, Entry/SL/TP touches, 21 streams
  orderflow.py  # CVD, delta z-score, book imbalance from aggTrade + depth10
  replay.py     # order-flow overlay validation against accrued history
  leaktest.py   # random-walk look-ahead regression test (must lose on coin flips)
k3.py           # CLI: top10 | universe | scan | backtest | research | leaktest | replay
reports/        # JSON artifacts of every run
```

## Safety

K3 outputs **setups, not orders**. STANDBY means a gate failed (funding, liquidity,
crowding, HTF conflict) — the system watches, it doesn't force trades. Futures with
leverage can liquidate you; nothing here is financial advice.
