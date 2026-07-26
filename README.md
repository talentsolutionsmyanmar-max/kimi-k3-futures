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

## Run it

```bash
pip install -r requirements.txt

python k3.py top10                              # live top-10 futures universe
python k3.py scan --profile both                # live setups, both profiles
python k3.py backtest --profile day --limit 1500
python k3.py research --profile scalp           # walk-forward validation
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

## Validation results (2026-07-26, live Binance data, $10k, fees+slippage+funding)

**DAY profile — 1200 bars × 10 symbols: 248 trades, 65.9% win, +$2,942 net** (avg +2.95%/symbol).
Best: DEXEU +$794 (PF 1.94), BANK +$675 (PF 2.34). Weakest: BTC −$319.

**SCALP profile — honest failure, documented on purpose.** Raw backtest: −$3,650
(BTC alone −$3,964 at 11% win rate). Walk-forward research (60 parameter combos/symbol,
train-gated then tested OOS): **no combo survived out-of-sample** (OOS PF 0.12–0.36).
Conclusion: the 5m stack is *not validated* in this market window; K3 ships it as
experimental and will not pretend otherwise. That refusal is the Fable5 provenance
doctrine working as intended.

**Live scan (16:52 UTC):** 4 WATCH setups — ESPORTS SHORT (structure −80, momentum −90,
funding z −1.88 contrarian), ETH/SOL/DOGE LONGs aligned with HTF — with full entry/stop/
3-TP plans. EULUSDT hard-blocked: funding 0.73% = extremely crowded.

## Architecture

```
k3/
  config.py     # risk kernel + SCALP/DAY profiles + fusion weights
  data.py       # Binance futures API: top10, klines(+taker flow), funding hist/z, OI, indicators
  structure.py  # swings, BOS/CHoCH state machine, displacement, FVG, premium/discount, OTE, sweeps, OBs
  signals.py    # 5-group signed scorers + composite K3 score + tiers + positioning overlay
  risk.py       # conviction-scaled sizing, TP ladder, portfolio caps
  engine.py     # per-symbol setup builder (structure → fusion → gates → trade plan)
  backtest.py   # funding-aware event-driven backtester, per-tier P&L
  research.py   # walk-forward grid validation with OOS honesty gate
k3.py           # CLI: top10 | scan | backtest | research
reports/        # JSON artifacts of every run
```

## Safety

K3 outputs **setups, not orders**. STANDBY means a gate failed (funding, liquidity,
crowding, HTF conflict) — the system watches, it doesn't force trades. Futures with
leverage can liquidate you; nothing here is financial advice.
